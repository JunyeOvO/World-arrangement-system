from __future__ import annotations

from typing import Any

from .attempt_recording import AttemptMetricsRecorder
from .policy_learning import PolicyLearningRecorder
from .stale_worker_reaper import StaleWorkerReaper
from .task_lifecycle import TaskLifecycleController
from .worker_permission_audit import WorkerPermissionAuditor


class ExecutionCallbackAdapter:
    """Callback facade shared by execution services and API adapters."""

    def __init__(
        self,
        *,
        lifecycle: TaskLifecycleController,
        policy_learning: PolicyLearningRecorder,
        permission_auditor: WorkerPermissionAuditor,
        attempt_metrics: AttemptMetricsRecorder,
        stale_worker_reaper: StaleWorkerReaper,
    ) -> None:
        self.lifecycle = lifecycle
        self.policy_learning = policy_learning
        self.permission_auditor = permission_auditor
        self.attempt_metrics = attempt_metrics
        self.stale_worker_reaper = stale_worker_reaper

    def record_policy_learning(
        self,
        task: dict[str, Any],
        project: dict[str, Any],
        success: bool,
        worker: str = "",
        model: str = "",
        variant: str = "",
        tests_passed: bool = False,
        codex_review_approved: bool = False,
        pr_created: bool = False,
        rollback: bool = False,
        incident: bool = False,
        changed_paths: list[str] | None = None,
    ) -> None:
        self.policy_learning.record_task_completion(
            task,
            project,
            success,
            worker=worker,
            model=model,
            variant=variant,
            tests_passed=tests_passed,
            codex_review_approved=codex_review_approved,
            pr_created=pr_created,
            rollback=rollback,
            incident=incident,
            changed_paths=changed_paths,
        )

    def set_status(self, task_id: str, status: str, event_type: str, payload: dict[str, Any]) -> None:
        self.lifecycle.set_status(task_id, status, event_type, payload)

    def check_worker_declared_permissions(self, task_id: str, worker_name: str, task: dict[str, Any]) -> dict[str, Any]:
        return self.permission_auditor.check_declared_permissions(task_id, worker_name, task)

    def check_worker_diff_permissions(self, task_id: str, worker_name: str, changed_files: list[str]) -> dict[str, Any]:
        return self.permission_auditor.check_diff_permissions(task_id, worker_name, changed_files)

    def write_attempt_metrics(
        self,
        task_id: str,
        attempt_no: int,
        attempt: dict[str, Any],
        worker_result: Any,
        failure: Any | None,
        build_passed: bool | None = None,
        review_approved: bool | None = None,
    ) -> None:
        self.attempt_metrics.write_attempt_metrics(
            task_id,
            attempt_no,
            attempt,
            worker_result,
            failure,
            build_passed=build_passed,
            review_approved=review_approved,
        )

    def write_token_ledger(self, task_id: str) -> None:
        self.attempt_metrics.write_token_ledger(task_id)

    def reap_stale_worker_task(self, task: dict[str, Any]) -> None:
        result = self.stale_worker_reaper.reap(task)
        if result:
            self.set_status(task["task_id"], result.status, result.event_type, result.payload)
