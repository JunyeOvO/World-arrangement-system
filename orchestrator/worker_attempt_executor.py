from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents_md import inject_agents_md
from .artifacts import ArtifactStore
from .attempt_recording import AttemptMetricsRecorder
from .failure_classifier import FailureClassification, classify_worker_failure
from .read_only_completion import read_only_failure_summary
from .worker_permission_audit import WorkerPermissionAuditor
from .workers.base import Worker, WorkerResult


@dataclass
class WorkerAttemptOutcome:
    kind: str
    attempt: dict[str, Any]
    worker_result: WorkerResult | None = None
    failure: FailureClassification | None = None
    permission: dict[str, Any] | None = None


class WorkerAttemptExecutor:
    """Runs one worker attempt and normalizes its immediate result."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        permission_auditor: WorkerPermissionAuditor,
        metrics_recorder: AttemptMetricsRecorder,
        workers: dict[str, Worker],
        default_worker: Worker,
        now: Callable[[], str],
        set_status: Callable[[str, str, str, dict[str, Any]], None],
        build_prompt: Callable[[dict[str, Any], dict[str, Any]], str],
    ) -> None:
        self.artifacts = artifacts
        self.permission_auditor = permission_auditor
        self.metrics_recorder = metrics_recorder
        self.workers = workers
        self.default_worker = default_worker
        self.now = now
        self.set_status = set_status
        self.build_prompt = build_prompt

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        worktree_path: Path,
        attempt: dict[str, Any],
        attempt_no: int,
        dry_run: bool = False,
    ) -> WorkerAttemptOutcome:
        attempt_dir = Path(task["run_dir"]) / "attempts" / f"{attempt_no:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        attempt["attempt_no"] = attempt_no
        attempt["started_at"] = self.now()

        preflight = self.permission_auditor.check_declared_permissions(task_id, attempt["worker"], task)
        if not preflight["allowed"]:
            failure = FailureClassification(
                "forbidden_path",
                False,
                "block_and_surface_policy_violation",
                [item["reason"] for item in preflight.get("denied", [])],
            )
            return WorkerAttemptOutcome("preflight_denied", attempt, failure=failure, permission=preflight)
        if preflight["requires_ask"]:
            return WorkerAttemptOutcome("preflight_requires_ask", attempt, permission=preflight)

        self._inject_attempt_agents_md(task_id, worktree_path, attempt, attempt_no)
        self.set_status(
            task_id,
            "EXECUTING",
            "worker_started",
            {"worker": attempt["worker"], "model": attempt["model"], "attempt": attempt_no, "variant": attempt.get("variant")},
        )

        worker = self.workers.get(attempt["worker"], self.default_worker)
        prompt = self.build_prompt(task, {"selected_model": attempt["model"], "selected_worker": attempt["worker"]})
        task_for_worker = {**task, "task_id": task_id}
        try:
            worker_result = worker.run(prompt, worktree_path, attempt, task_for_worker, dry_run=dry_run)
        except Exception as exc:
            failure = FailureClassification(
                "worker_exception",
                False,
                "inspect_worker_control_files",
                [str(exc)],
            )
            attempt["finished_at"] = self.now()
            attempt["status"] = "failed"
            attempt["failure_reason"] = failure.failure_reason
            attempt["failure"] = failure.to_dict()
            self.artifacts.write_json(task_id, f"attempts/{attempt_no:02d}/result.json", attempt)
            return WorkerAttemptOutcome("worker_exception", attempt, failure=failure)

        diff_permissions = self.permission_auditor.check_diff_permissions(
            task_id,
            attempt["worker"],
            worker_result.changed_files,
        )
        if not diff_permissions["allowed"]:
            failure = FailureClassification(
                "forbidden_path",
                False,
                "block_and_surface_policy_violation",
                [item["reason"] for item in diff_permissions.get("denied", [])],
            )
            worker_result.status = "blocked"
            worker_result.risks.extend([item["reason"] for item in diff_permissions.get("denied", [])])
            self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
            return WorkerAttemptOutcome(
                "diff_denied",
                attempt,
                worker_result=worker_result,
                failure=failure,
                permission=diff_permissions,
            )
        if diff_permissions["requires_ask"]:
            return WorkerAttemptOutcome("diff_requires_ask", attempt, worker_result=worker_result, permission=diff_permissions)

        failure = self._finalize_worker_result(task, task_id, attempt, attempt_no, worker_result)
        return WorkerAttemptOutcome("completed", attempt, worker_result=worker_result, failure=failure)

    def _inject_attempt_agents_md(
        self,
        task_id: str,
        worktree_path: Path,
        attempt: dict[str, Any],
        attempt_no: int,
    ) -> None:
        if attempt["worker"] != "opencode":
            return
        attempt_inject = inject_agents_md(worktree_path)
        self.artifacts.write_json(task_id, f"attempts/{attempt_no:02d}/agents_md.json", attempt_inject.__dict__)
        if not attempt_inject.injected:
            self.set_status(task_id, "EXECUTING", "agents_md_skipped", attempt_inject.__dict__)

    def _finalize_worker_result(
        self,
        task: dict[str, Any],
        task_id: str,
        attempt: dict[str, Any],
        attempt_no: int,
        worker_result: WorkerResult,
    ) -> FailureClassification | None:
        attempt["finished_at"] = self.now()
        attempt["status"] = worker_result.status
        attempt["summary"] = worker_result.summary
        failure = None
        if worker_result.status != "success":
            failure = classify_worker_failure(
                status=worker_result.status,
                summary=worker_result.summary,
                risks=worker_result.risks,
                changed_files=worker_result.changed_files,
                stdout_path=worker_result.stdout_path,
                stderr_path=worker_result.stderr_path,
            )
            attempt["failure_reason"] = failure.failure_reason
            attempt["failure"] = failure.to_dict()
            salvaged_summary = read_only_failure_summary(task, worker_result, failure)
            if salvaged_summary:
                worker_result.status = "success"
                worker_result.summary = salvaged_summary
                worker_result.risks.append("read_only_no_diff_salvaged_from_worker_failure")
                attempt["status"] = "success"
                attempt["summary"] = salvaged_summary
                attempt.pop("failure_reason", None)
                attempt.pop("failure", None)
                failure = None

        self.artifacts.write_json(task_id, f"attempts/{attempt_no:02d}/result.json", attempt)
        self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
        self.metrics_recorder.write_attempt_metrics(task_id, attempt_no, attempt, worker_result, failure)
        return failure
