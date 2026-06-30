"""Completion tail pipeline after worker attempts succeed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .read_only_completion import read_only_result_can_finish
from .task_result_document import build_final_markdown


@dataclass
class CompletionPipelineResult:
    status: str | None = None
    event_type: str | None = None
    completed: bool = True


class TaskCompletionPipeline:
    """Runs degraded/read-only/verify/review/publish tail for a final worker result."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        terminal_handler,
        verification_runner,
        review_runner,
        publish_runner,
        set_status: Callable[[str, str, str, dict[str, Any]], None],
        record_policy_learning: Callable[..., None],
        write_attempt_metrics: Callable[..., None],
    ) -> None:
        self.artifacts = artifacts
        self.terminal_handler = terminal_handler
        self.verification_runner = verification_runner
        self.review_runner = review_runner
        self.publish_runner = publish_runner
        self.set_status = set_status
        self.record_policy_learning = record_policy_learning
        self.write_attempt_metrics = write_attempt_metrics

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        project: dict[str, Any],
        route: dict[str, Any],
        worker_result: Any,
        last_attempt: dict[str, Any] | None,
        worktree_path: Path,
        branch: str,
        dry_run: bool = False,
    ) -> CompletionPipelineResult:
        if worker_result_is_degraded_mock(worker_result):
            terminal = self.terminal_handler.handle_degraded_mock(
                task_id=task_id,
                task=task,
                route=route,
                worker_result=worker_result,
                last_attempt=last_attempt,
                dry_run=dry_run,
            )
            self.set_status(task_id, terminal.status, terminal.event_type, terminal.payload)
            self.record_policy_learning(
                task,
                project,
                success=terminal.policy_success,
                worker=route["selected_worker"],
                model=route["selected_model"],
            )
            return CompletionPipelineResult(terminal.status, terminal.event_type)

        self.set_status(task_id, "VERIFYING", "verify_started", {})
        verification = self.verification_runner.run(
            task_id=task_id,
            task=task,
            worktree_path=worktree_path,
            worker_result=worker_result,
            last_attempt=last_attempt,
            dry_run=dry_run,
        )
        verify_result = verification.verify_result
        forbidden = verification.forbidden

        if not verification.passed:
            failure = verification.failure
            assert failure is not None
            if last_attempt:
                self.write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    worker_result,
                    failure,
                    build_passed=verify_result.build_passed,
                )
            self.set_status(
                task_id,
                "FAILED_FINAL",
                "verify_failed",
                {
                    "failure_reason": failure.failure_reason,
                    "failure": failure.to_dict(),
                    "verify": verify_result.to_dict(),
                    "forbidden": forbidden.__dict__,
                },
            )
            self.record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return CompletionPipelineResult("FAILED_FINAL", "verify_failed")

        if read_only_result_can_finish(task, worker_result):
            terminal = self.terminal_handler.handle_read_only_completion(
                task_id=task_id,
                task=task,
                route=route,
                worker_result=worker_result,
                verify_result=verify_result,
                forbidden=forbidden,
                last_attempt=last_attempt,
                dry_run=dry_run,
            )
            self.set_status(task_id, terminal.status, terminal.event_type, terminal.payload)
            self.record_policy_learning(
                task,
                project,
                success=terminal.policy_success,
                worker=route["selected_worker"],
                model=route["selected_model"],
                tests_passed=terminal.tests_passed,
                codex_review_approved=terminal.codex_review_approved,
                changed_paths=terminal.changed_paths or [],
            )
            return CompletionPipelineResult(terminal.status, terminal.event_type)

        self.set_status(task_id, "CODEX_REVIEWING", "review_started", {})
        review_outcome = self.review_runner.run(
            task_id=task_id,
            task=task,
            verify_result=verify_result,
            forbidden=forbidden,
            dry_run=dry_run,
        )
        review = review_outcome.review
        if review_outcome.degraded_blocks_publish:
            failure = review_outcome.failure
            assert failure is not None
            if last_attempt:
                self.write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    worker_result,
                    failure,
                    build_passed=verify_result.build_passed,
                    review_approved=False,
                )
            self.artifacts.write_text(
                task_id,
                "final.md",
                build_final_markdown(task, route, worker_result.__dict__, verify_result.to_dict(), review),
            )
            self.set_status(
                task_id,
                "NEEDS_REVIEW",
                "review_degraded_needs_review",
                {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "review": review},
            )
            self.record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return CompletionPipelineResult("NEEDS_REVIEW", "review_degraded_needs_review")

        if not review_outcome.passed:
            failure = review_outcome.failure
            assert failure is not None
            if last_attempt:
                self.write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    worker_result,
                    failure,
                    build_passed=verify_result.build_passed,
                    review_approved=False,
                )
            self.set_status(
                task_id,
                "FAILED_FINAL",
                "review_failed",
                {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "review": review},
            )
            self.record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return CompletionPipelineResult("FAILED_FINAL", "review_failed")

        if last_attempt:
            self.write_attempt_metrics(
                task_id,
                int(last_attempt.get("attempt_no", 1)),
                last_attempt,
                worker_result,
                None,
                build_passed=verify_result.build_passed,
                review_approved=True,
            )

        self.set_status(task_id, "POLICY_LEARNING", "policy_learning", {})
        self.record_policy_learning(
            task,
            project,
            success=True,
            worker=route["selected_worker"],
            model=route["selected_model"],
            tests_passed=verify_result.tests_passed,
            codex_review_approved=review.get("approved", False),
            changed_paths=verify_result.changed_files,
        )

        self.set_status(task_id, "PLANNED", "review_passed", review)
        final = build_final_markdown(task, route, worker_result.__dict__, verify_result.to_dict(), review)
        self.artifacts.write_text(task_id, "final.md", final)

        publish = self.publish_runner.run(
            task_id=task_id,
            task=task,
            project=project,
            worktree_path=worktree_path,
            branch=branch,
        )
        self.set_status(task_id, publish.status, publish.event_type, publish.payload)
        if publish.pr_created:
            self.record_policy_learning(
                task,
                project,
                success=True,
                worker=route["selected_worker"],
                model=route["selected_model"],
                pr_created=True,
            )
        return CompletionPipelineResult(publish.status, publish.event_type)


def worker_result_is_degraded_mock(result: Any) -> bool:
    return (
        bool(getattr(result, "mock_result", False))
        or bool(getattr(result, "degraded", False))
        or str(getattr(result, "status", "")).lower() == "mock"
    )
