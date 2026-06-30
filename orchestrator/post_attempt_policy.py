from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .failure_classifier import FailureClassification, classify_worker_failure
from .read_only_completion import task_requires_diff
from .worker_attempts import should_recover_failed_worker_diff


@dataclass
class PostAttemptDecision:
    kind: str
    status: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None
    failure: FailureClassification | None = None


def decide_post_attempt(
    *,
    task: dict[str, Any],
    worker_result: Any,
    failure: FailureClassification | None,
    attempt: dict[str, Any],
    attempt_index: int,
    retry_chain: list[dict[str, Any]],
    dry_run: bool,
    worker_name: str,
) -> PostAttemptDecision:
    if worker_result.status == "success":
        if not dry_run and task_requires_diff(task) and not worker_result.changed_files:
            worker_result.status = "failed"
            worker_result.summary = f"{worker_name} completed without producing a diff"
            worker_result.risks.append("worker_no_diff")
            no_diff_failure = classify_worker_failure(
                status=worker_result.status,
                summary=worker_result.summary,
                risks=worker_result.risks,
                changed_files=worker_result.changed_files,
                stdout_path=worker_result.stdout_path,
                stderr_path=worker_result.stderr_path,
            )
            return PostAttemptDecision(
                "no_diff",
                status="RETRYING" if attempt_index + 1 < len(retry_chain) else "FAILED_FINAL",
                event_type="worker_no_diff",
                payload={**worker_result.__dict__, "failure": no_diff_failure.to_dict()},
                failure=no_diff_failure,
            )
        return PostAttemptDecision("success")

    if should_recover_failed_worker_diff(worker_result):
        worker_result.risks.append("scheduler_recover_failed_worker_diff")
        return PostAttemptDecision(
            "recover_failed_diff",
            status="EXECUTING",
            event_type="worker_failed_with_diff",
            payload={**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
            failure=failure,
        )

    if worker_result.status == "blocked":
        return PostAttemptDecision(
            "blocked",
            status="BLOCKED",
            event_type="worker_blocked",
            payload={**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
            failure=failure,
        )

    if worker_result.status == "cancelled":
        return PostAttemptDecision(
            "cancelled",
            status="CANCELLED",
            event_type="worker_cancelled",
            payload={**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
            failure=failure,
        )

    if failure and not failure.retryable:
        return PostAttemptDecision(
            "non_retryable_failure",
            status="FAILED_FINAL",
            event_type="worker_non_retryable_failure",
            payload={"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "attempt": attempt_index + 1},
            failure=failure,
        )

    if attempt_index + 1 < len(retry_chain):
        next_attempt = retry_chain[attempt_index + 1]
        return PostAttemptDecision(
            "retry",
            status="RETRYING",
            event_type="worker_retry",
            payload={
                "failed_attempt": attempt_index + 1,
                "failed_worker": attempt["worker"],
                "next_worker": next_attempt["worker"],
                "next_model": next_attempt["model"],
                "reason": failure.failure_reason if failure else attempt.get("reason", "worker_failed"),
                "failure": failure.to_dict() if failure else None,
            },
            failure=failure,
        )

    return PostAttemptDecision("attempts_exhausted", failure=failure)
