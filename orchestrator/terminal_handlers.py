from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .attempt_recording import AttemptMetricsRecorder
from .failure_classifier import classify_review_failure
from .read_only_completion import read_only_review
from .task_result_document import build_final_markdown
from .verifier import VerifyResult, write_verify_result


@dataclass
class TerminalHandlingResult:
    status: str
    event_type: str
    payload: dict[str, Any]
    policy_success: bool
    tests_passed: bool = False
    codex_review_approved: bool = False
    changed_paths: list[str] | None = None


class TerminalTaskHandler:
    """Handles terminal task paths that bypass the normal review/publish flow."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        metrics_recorder: AttemptMetricsRecorder,
        dry_verify_func: Callable[[dict[str, Any]], VerifyResult],
        record_review_codex_usage: Callable[[str, dict[str, Any], dict[str, Any]], None],
    ) -> None:
        self.artifacts = artifacts
        self.metrics_recorder = metrics_recorder
        self.dry_verify_func = dry_verify_func
        self.record_review_codex_usage = record_review_codex_usage

    def handle_degraded_mock(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        route: dict[str, Any],
        worker_result: Any,
        last_attempt: dict[str, Any] | None,
        dry_run: bool,
    ) -> TerminalHandlingResult:
        verify_result = self.dry_verify_func(task)
        write_verify_result(verify_result, Path(task["run_dir"]) / "verify" / "verify.json")
        self.artifacts.write_json(task_id, "verify/changed_files.json", verify_result.changed_files)
        review = degraded_mock_review(task, worker_result, dry_run=dry_run)
        self.artifacts.write_json(task_id, "review/review.json", review)
        self.record_review_codex_usage(
            task_id,
            {
                "task_id": task_id,
                "risk_level": task["risk_level"],
                "dry_run": dry_run,
                "tests_passed": verify_result.tests_passed,
                "forbidden_paths_touched": False,
                "changed_files": verify_result.changed_files,
                "worker_degraded_mock": True,
            },
            review,
        )
        self.artifacts.write_text(
            task_id,
            "final.md",
            build_final_markdown(task, route, worker_result.__dict__, verify_result.to_dict(), review),
        )
        if last_attempt:
            failure = classify_review_failure({**review, "available": False})
            self.metrics_recorder.write_attempt_metrics(
                task_id,
                int(last_attempt.get("attempt_no", 1)),
                last_attempt,
                worker_result,
                failure,
                build_passed=verify_result.build_passed,
                review_approved=False,
            )
        if dry_run:
            return TerminalHandlingResult(
                status="DRY_RUN_COMPLETED",
                event_type="dry_run_completed",
                payload={"worker": worker_result.__dict__, "review": review},
                policy_success=False,
            )
        return TerminalHandlingResult(
            status="NEEDS_USER",
            event_type="worker_degraded_mock_needs_user",
            payload={"worker": worker_result.__dict__, "review": review},
            policy_success=False,
        )

    def handle_read_only_completion(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        route: dict[str, Any],
        worker_result: Any,
        verify_result: Any,
        forbidden: Any,
        last_attempt: dict[str, Any] | None,
        dry_run: bool,
    ) -> TerminalHandlingResult:
        partial_result = bool(getattr(worker_result, "partial_result", False))
        completion_status = "COMPLETED_WITH_PARTIAL_ARTIFACTS" if partial_result else "COMPLETED_WITH_ARTIFACTS"
        completion_event = "read_only_partial_completed" if partial_result else "read_only_completed"
        review = read_only_review(
            task,
            "read_only_partial_salvage" if partial_result else "read_only_no_diff",
        )
        self.artifacts.write_json(task_id, "review/review.json", review)
        self.record_review_codex_usage(
            task_id,
            {
                "task_id": task_id,
                "risk_level": task["risk_level"],
                "dry_run": dry_run,
                "tests_passed": verify_result.tests_passed,
                "forbidden_paths_touched": not forbidden.allowed,
                "changed_files": verify_result.changed_files,
                "read_only": True,
            },
            review,
        )
        self.artifacts.write_text(
            task_id,
            "final.md",
            build_final_markdown(task, route, worker_result.__dict__, verify_result.to_dict(), review),
        )
        if last_attempt:
            self.metrics_recorder.write_attempt_metrics(
                task_id,
                int(last_attempt.get("attempt_no", 1)),
                last_attempt,
                worker_result,
                None,
                build_passed=verify_result.build_passed,
                review_approved=True,
            )
        return TerminalHandlingResult(
            status=completion_status,
            event_type=completion_event,
            payload={"worker": worker_result.__dict__, "verify": verify_result.to_dict(), "review": review},
            policy_success=True,
            tests_passed=verify_result.tests_passed,
            codex_review_approved=True,
            changed_paths=[],
        )


def degraded_mock_review(task: dict[str, Any], worker_result: Any, dry_run: bool) -> dict[str, Any]:
    reason = getattr(worker_result, "degradation_reason", None) or "worker returned a mock result"
    return {
        "approved": False,
        "review_mode": "degraded_mock",
        "degraded": True,
        "degradation_reason": reason,
        "available": False,
        "risk_level": task.get("risk_level", "medium"),
        "blocking_issues": ["real worker execution was not available"],
        "non_blocking_issues": [],
        "required_changes": ["run the task with an available real worker before treating this as analysis"],
        "final_recommendation": "do not treat this result as a real audit or implementation",
        "can_create_pr": False,
        "dry_run": dry_run,
        "mock_result": True,
    }
