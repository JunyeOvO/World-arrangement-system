from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import time
from typing import Any


QUEUED_STATUSES = {
    "NEW",
    "QUEUED",
    "CLASSIFIED",
    "RISK_EVALUATED",
    "DYNAMIC_RISK_SCORED",
    "APPROVAL_DECIDED",
    "AUTO_SILENT",
    "AUTO_WITH_SUMMARY",
    "PLANNED",
    "ROUTED",
    "WORKTREE_CREATED",
    "WORKTREE_READY",
}

ACTIVE_STATUSES = {
    "EXECUTING",
    "RUNNING",
    "VERIFYING",
    "CODEX_REVIEWING",
    "REVIEWING",
    "PUBLISHING",
}

APPROVAL_STATUSES = {
    "HARD_APPROVAL_WAITING",
    "SOFT_APPROVAL_WAITING",
    "NEEDS_USER",
    "NEEDS_REVIEW",
    "BLOCKED",
}

FAILED_STATUSES = {
    "FAILED",
    "FAILED_FINAL",
    "WORKER_FAILED",
    "WORKER_TIMED_OUT",
    "VERIFY_FAILED",
    "REVIEW_FAILED",
    "PUBLISH_FAILED",
}

DONE_STATUSES = {
    "DONE",
    "COMPLETED",
    "COMPLETED_WITH_PATCH",
    "COMPLETED_NO_CHANGES",
    "COMPLETED_WITH_ARTIFACTS",
    "DRY_RUN_COMPLETED",
    "PR_CREATED",
}

CLOSED_STATUSES = {
    "CANCELLED",
    "ROLLED_BACK",
    "DONE_WITH_BLOCK",
}

ALERT_STATUSES = {
    "STALE_EXECUTING",
    "STALE_RUNNING",
    "STALE_VERIFYING",
    "STALE_CODEX_REVIEWING",
    "STALE_REVIEWING",
    "STALE_PUBLISHING",
    "ORPHAN_WORKTREE",
    "MISSING_ARTIFACTS",
    "DB_PROCESS_MISMATCH",
    "UNKNOWN_STATUS",
    "RETRY_STUCK",
    "ESCALATION_STUCK",
    "PUBLISHING_STUCK",
    "CONTROL_HEARTBEAT_MISSING",
}

BIG_TO_CONSOLE_GROUP = {
    "Running": "running",
    "Queued": "queued",
    "Failed": "failed",
    "Approval": "approval",
    "Alerts": "alerts",
    "Done": "none",
    "Closed": "none",
}


@dataclass(frozen=True)
class DashboardStatus:
    raw_status: str
    display_status: str
    big_status: str
    console_group: str
    is_terminal: bool
    requires_user_action: bool
    is_live: bool
    is_stale: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_dashboard_status(
    task: dict[str, Any],
    *,
    heartbeat_fresh: bool = False,
    control_process: dict[str, Any] | None = None,
    has_missing_artifacts: bool = False,
    has_orphan_worktree: bool = False,
    retry_scheduler_reliable: bool = False,
    now_ts: float | None = None,
) -> DashboardStatus:
    raw = str(task.get("status") or task.get("raw_status") or "UNKNOWN").upper()
    process_status = str((control_process or {}).get("status") or "").lower()

    if process_status in {"failed", "timed_out"}:
        display = "WORKER_FAILED" if process_status == "failed" else "WORKER_TIMED_OUT"
        return _status(raw, display, "Failed", False, False, False, False, f"control process is {process_status}")

    if has_missing_artifacts:
        return _status(raw, "MISSING_ARTIFACTS", "Alerts", False, False, False, False, "required task artifacts are missing")

    if has_orphan_worktree:
        return _status(raw, "ORPHAN_WORKTREE", "Alerts", False, False, False, False, "worktree exists without a coherent task lifecycle")

    if raw == "RETRYING":
        next_attempt_at = task.get("next_attempt_at")
        if retry_scheduler_reliable and next_attempt_at:
            due = _parse_ts(next_attempt_at)
            if due is not None and (now_ts or time.time()) < due:
                return _status(raw, "RETRY_SCHEDULED", "Queued", False, False, False, False, "retry is scheduled")
            if heartbeat_fresh:
                return _status(raw, "RETRYING", "Running", False, False, True, False, "retry worker heartbeat is fresh")
        return _status(raw, "RETRY_STUCK", "Alerts", False, False, False, True, "retry has no reliable scheduler state")

    if raw == "ESCALATED":
        if task.get("next_attempt_at"):
            return _status(raw, "ESCALATED", "Queued", False, False, False, False, "escalated attempt is scheduled")
        return _status(raw, "ESCALATION_STUCK", "Alerts", False, False, False, True, "escalation has no next attempt")

    if raw in ACTIVE_STATUSES:
        if heartbeat_fresh:
            return _status(raw, raw, "Running", False, False, True, False, "active task has fresh heartbeat")
        return _status(raw, f"STALE_{raw}", "Alerts", False, False, False, True, "active task has no fresh heartbeat")

    if raw in APPROVAL_STATUSES:
        return _status(raw, raw, "Approval", False, True, False, False, "task requires user action")

    if raw in QUEUED_STATUSES:
        return _status(raw, raw, "Queued", False, False, False, False, "task can continue automatically")

    if raw in FAILED_STATUSES:
        return _status(raw, raw, "Failed", True, False, False, False, "task failed and cannot continue automatically")

    if raw in DONE_STATUSES:
        return _status(raw, raw, "Done", True, False, False, False, "task completed")

    if raw in CLOSED_STATUSES:
        return _status(raw, raw, "Closed", True, False, False, False, "task is closed")

    return _status(raw, "UNKNOWN_STATUS", "Alerts", False, False, False, True, f"unknown raw status: {raw}")


def compute_top_status_counts(tasks: list[dict[str, Any]], system_alert_count: int = 0) -> dict[str, int]:
    counts = {"running": 0, "queued": 0, "failed": 0, "approval_waiting": 0, "alerts": system_alert_count}
    for task in tasks:
        group = str(task.get("console_group") or "").lower()
        if group == "running":
            counts["running"] += 1
        elif group == "queued":
            counts["queued"] += 1
        elif group == "failed":
            counts["failed"] += 1
        elif group == "approval":
            counts["approval_waiting"] += 1
        elif group == "alerts":
            counts["alerts"] += 1
    return counts


def _status(
    raw_status: str,
    display_status: str,
    big_status: str,
    is_terminal: bool,
    requires_user_action: bool,
    is_live: bool,
    is_stale: bool,
    reason: str,
) -> DashboardStatus:
    return DashboardStatus(
        raw_status=raw_status,
        display_status=display_status,
        big_status=big_status,
        console_group=BIG_TO_CONSOLE_GROUP[big_status],
        is_terminal=is_terminal,
        requires_user_action=requires_user_action,
        is_live=is_live,
        is_stale=is_stale,
        reason=reason,
    )


def _parse_ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
