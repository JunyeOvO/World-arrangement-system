"""Worker retry-attempt sequencing for task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .failure_classifier import FailureClassification
from .post_attempt_policy import decide_post_attempt
from .task_protocol import apply_read_budget_to_route
from .worker_attempts import build_retry_chain


@dataclass
class AttemptPolicySignal:
    success: bool
    worker: str = ""
    model: str = ""
    rollback: bool = False
    incident: bool = False


@dataclass
class AttemptRunResult:
    final_result: Any | None = None
    last_attempt: dict[str, Any] | None = None
    terminal_status: str | None = None
    terminal_event: str | None = None
    terminal_payload: dict[str, Any] = field(default_factory=dict)
    policy_signal: AttemptPolicySignal | None = None

    @property
    def completed(self) -> bool:
        return self.final_result is not None


class TaskAttemptRunner:
    """Runs retry chains and converts worker outcomes to scheduler-level results."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        attempt_executor,
        workers: dict[str, Any],
        default_worker,
        set_status: Callable[[str, str, str, dict[str, Any]], None],
        write_attempt_metrics: Callable[..., None],
    ) -> None:
        self.artifacts = artifacts
        self.attempt_executor = attempt_executor
        self.workers = workers
        self.default_worker = default_worker
        self.set_status = set_status
        self.write_attempt_metrics = write_attempt_metrics

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        route: dict[str, Any],
        worktree_path: Path,
        dry_run: bool = False,
    ) -> AttemptRunResult:
        retry_chain = build_retry_chain(route, task)
        last_failure: FailureClassification | None = None
        last_attempt: dict[str, Any] | None = None

        for idx, attempt in enumerate(retry_chain):
            attempt = apply_read_budget_to_route(attempt, task)
            outcome = self.attempt_executor.run(
                task_id=task_id,
                task=task,
                worktree_path=worktree_path,
                attempt=attempt,
                attempt_no=idx + 1,
                dry_run=dry_run,
            )
            attempt = outcome.attempt
            worker_result = outcome.worker_result
            failure = outcome.failure

            immediate = self._terminal_for_worker_outcome(task_id, outcome, failure, attempt, idx)
            if immediate:
                return immediate

            assert worker_result is not None
            if failure:
                last_failure = failure
                last_attempt = attempt

            decision = decide_post_attempt(
                task=task,
                worker_result=worker_result,
                failure=failure,
                attempt=attempt,
                attempt_index=idx,
                retry_chain=retry_chain,
                dry_run=dry_run,
                worker_name=self.workers.get(attempt["worker"], self.default_worker).name,
            )

            if decision.kind == "success":
                return AttemptRunResult(final_result=worker_result, last_attempt=attempt)

            if decision.kind == "no_diff":
                failure = decision.failure
                last_failure = failure
                last_attempt = attempt
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                self.write_attempt_metrics(task_id, idx + 1, attempt, worker_result, failure)
                if idx + 1 < len(retry_chain):
                    self._record_transition(task_id, decision.status, decision.event_type, decision.payload or {})
                    continue
                return AttemptRunResult(
                    terminal_status=decision.status,
                    terminal_event=decision.event_type,
                    terminal_payload=decision.payload or {},
                    policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], rollback=True),
                )

            if decision.kind == "recover_failed_diff":
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                return AttemptRunResult(
                    final_result=worker_result,
                    last_attempt=attempt,
                    terminal_status=decision.status,
                    terminal_event=decision.event_type,
                    terminal_payload=decision.payload or {},
                )

            if decision.kind == "blocked":
                return AttemptRunResult(
                    terminal_status=decision.status,
                    terminal_event=decision.event_type,
                    terminal_payload=decision.payload or {},
                    policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
                )

            if decision.kind == "cancelled":
                return AttemptRunResult(
                    terminal_status=decision.status,
                    terminal_event=decision.event_type,
                    terminal_payload=decision.payload or {},
                )

            if decision.kind == "non_retryable_failure":
                return AttemptRunResult(
                    terminal_status=decision.status,
                    terminal_event=decision.event_type,
                    terminal_payload=decision.payload or {},
                    policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
                )

            if decision.kind == "retry":
                self._record_transition(task_id, decision.status, decision.event_type, decision.payload or {})
                continue

        payload = {"total_attempts": len(retry_chain)}
        if last_failure:
            payload.update({"failure_reason": last_failure.failure_reason, "failure": last_failure.to_dict()})
        if last_attempt:
            payload["last_attempt"] = {
                "worker": last_attempt.get("worker"),
                "model": last_attempt.get("model"),
                "attempt": last_attempt.get("attempt_no"),
            }
        last_route = retry_chain[-1] if retry_chain else {}
        return AttemptRunResult(
            terminal_status="FAILED_FINAL",
            terminal_event="all_attempts_failed",
            terminal_payload=payload,
            policy_signal=AttemptPolicySignal(
                False,
                last_route.get("worker", ""),
                last_route.get("model", ""),
                rollback=True,
            ),
        )

    def _terminal_for_worker_outcome(
        self,
        task_id: str,
        outcome,
        failure: FailureClassification | None,
        attempt: dict[str, Any],
        idx: int,
    ) -> AttemptRunResult | None:
        if outcome.kind == "preflight_denied":
            return AttemptRunResult(
                terminal_status="BLOCKED",
                terminal_event="permission_denied",
                terminal_payload={"phase": "preflight", "permission": outcome.permission, "failure": failure.to_dict() if failure else None},
                policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
            )
        if outcome.kind == "preflight_requires_ask":
            self.artifacts.write_text(
                task_id,
                "approval_explanation.md",
                "Static worker permissions require explicit approval for declared write paths.\n",
            )
            return AttemptRunResult(
                terminal_status="HARD_APPROVAL_WAITING",
                terminal_event="permission_requires_approval",
                terminal_payload={"phase": "preflight", "permission": outcome.permission},
            )
        if outcome.kind == "worker_exception":
            assert failure is not None
            return AttemptRunResult(
                terminal_status="FAILED_FINAL",
                terminal_event="worker_exception",
                terminal_payload={"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "attempt": idx + 1},
                policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
            )
        if outcome.kind == "diff_denied":
            return AttemptRunResult(
                terminal_status="BLOCKED",
                terminal_event="permission_denied",
                terminal_payload={"phase": "diff", "permission": outcome.permission, "failure": failure.to_dict() if failure else None},
                policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
            )
        if outcome.kind == "diff_requires_ask":
            return AttemptRunResult(
                terminal_status="HARD_APPROVAL_WAITING",
                terminal_event="permission_requires_approval",
                terminal_payload={"phase": "diff", "permission": outcome.permission},
            )
        if outcome.kind != "completed" or outcome.worker_result is None:
            return AttemptRunResult(
                terminal_status="FAILED_FINAL",
                terminal_event="worker_unknown_attempt_outcome",
                terminal_payload={"attempt": idx + 1, "kind": outcome.kind},
                policy_signal=AttemptPolicySignal(False, attempt["worker"], attempt["model"], incident=True),
            )
        return None

    def _record_transition(self, task_id: str, status: str | None, event_type: str | None, payload: dict[str, Any]) -> None:
        if status and event_type:
            self.set_status(task_id, status, event_type, payload)
