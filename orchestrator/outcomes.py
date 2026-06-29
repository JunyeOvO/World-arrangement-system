from __future__ import annotations

import time
from typing import Any


SUCCESS_STATUSES = {
    "COMPLETED_WITH_PATCH",
    "COMPLETED_NO_CHANGES",
    "COMPLETED_WITH_ARTIFACTS",
    "COMPLETED_WITH_PARTIAL_ARTIFACTS",
    "PR_CREATED",
    "DONE",
    "DRY_RUN_COMPLETED",
}
FAILED_STATUSES = {"FAILED", "FAILED_FINAL"}
APPROVAL_STATUSES = {
    "HARD_APPROVAL_WAITING",
    "SOFT_APPROVAL_WAITING",
    "NEEDS_USER",
    "NEEDS_REVIEW",
}
BLOCKED_STATUSES = {"BLOCKED"}
CANCELLED_STATUSES = {"CANCELLED"}
OUTCOME_STATUSES = SUCCESS_STATUSES | FAILED_STATUSES | APPROVAL_STATUSES | BLOCKED_STATUSES | CANCELLED_STATUSES


def should_record_outcome(status: str) -> bool:
    return str(status or "") in OUTCOME_STATUSES


def derive_task_outcome(
    task: dict[str, Any],
    metrics: list[dict[str, Any]] | None = None,
    task_artifact: dict[str, Any] | None = None,
    verify: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = metrics or []
    task_artifact = task_artifact or {}
    verify = verify or {}
    review = review or {}
    result = result or {}
    status = str(task.get("status") or "")
    now = _now()
    changed_files_count = _changed_files_count(metrics, verify, result)
    tests_passed = _first_bool(verify.get("tests_passed"), _metric_bool(metrics, "build_passed"))
    build_passed = _first_bool(verify.get("build_passed"), _metric_bool(metrics, "build_passed"))
    review_approved = _first_bool(review.get("approved"), _metric_bool(metrics, "review_approved"))
    degraded = bool(review.get("degraded") or result.get("degraded") or result.get("mock_result"))
    mock_result = bool(result.get("mock_result") or _metadata_flag(metrics, "mock_result"))
    outcome = _outcome_bucket(status, degraded=degraded, mock_result=mock_result)
    acceptance = _acceptance(status, review_approved=review_approved, degraded=degraded)
    return {
        "task_id": task.get("task_id"),
        "project_id": task.get("project_id"),
        "task_type": task_artifact.get("task_type") or _classify_goal(str(task.get("user_goal") or "")),
        "risk_level": task_artifact.get("risk_level") or "medium",
        "route_worker": task.get("route_worker"),
        "route_model": task.get("route_model"),
        "terminal_status": status,
        "outcome": outcome,
        "quality_state": _quality_state(outcome, tests_passed, build_passed, review_approved, degraded),
        "user_acceptance": acceptance,
        "changed_files_count": changed_files_count,
        "tests_passed": tests_passed,
        "build_passed": build_passed,
        "review_approved": review_approved,
        "degraded": degraded,
        "mock_result": mock_result,
        "codex_rework_required": _codex_rework_required(outcome, degraded, review),
        "created_at": task.get("created_at") or now,
        "updated_at": task.get("updated_at") or now,
        "completed_at": task.get("updated_at") or now,
        "metadata": {
            **(metadata or {}),
            "metric_attempts": len(metrics),
            "review_mode": review.get("review_mode"),
            "failure_reason": _failure_reason(metrics, review, result),
        },
    }


def summarize_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    success = sum(1 for row in rows if row.get("outcome") == "success")
    failed = sum(1 for row in rows if row.get("outcome") == "failed")
    approval = sum(1 for row in rows if row.get("outcome") == "approval")
    degraded = sum(1 for row in rows if row.get("degraded"))
    mock = sum(1 for row in rows if row.get("mock_result"))
    rework = sum(1 for row in rows if row.get("codex_rework_required"))
    accepted = sum(1 for row in rows if row.get("user_acceptance") == "accepted")
    rejected = sum(1 for row in rows if row.get("user_acceptance") == "rejected")
    tests_passed = sum(1 for row in rows if _truthy_bool(row.get("tests_passed")))
    review_approved = sum(1 for row in rows if _truthy_bool(row.get("review_approved")))
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "approval": approval,
        "degraded": degraded,
        "mock_result": mock,
        "codex_rework_required": rework,
        "accepted": accepted,
        "rejected": rejected,
        "success_rate": _pct(success, total),
        "known_acceptance_rate": _pct(accepted, accepted + rejected),
        "tests_pass_rate": _pct(tests_passed, total),
        "review_approval_rate": _pct(review_approved, total),
        "degraded_rate": _pct(degraded, total),
        "rework_rate": _pct(rework, total),
        "by_task_type": _group_counts(rows, "task_type"),
        "by_model": _group_counts(rows, "route_model"),
    }


def _outcome_bucket(status: str, degraded: bool, mock_result: bool) -> str:
    if status in SUCCESS_STATUSES:
        return "degraded" if degraded or mock_result else "success"
    if status in FAILED_STATUSES or status in BLOCKED_STATUSES:
        return "failed"
    if status in APPROVAL_STATUSES:
        return "approval"
    if status in CANCELLED_STATUSES:
        return "cancelled"
    return "unknown"


def _quality_state(
    outcome: str,
    tests_passed: bool | None,
    build_passed: bool | None,
    review_approved: bool | None,
    degraded: bool,
) -> str:
    if outcome == "success" and tests_passed is not False and build_passed is not False and review_approved is not False:
        return "verified"
    if degraded:
        return "degraded"
    if outcome == "approval":
        return "needs_user"
    if outcome in {"failed", "cancelled"}:
        return outcome
    return "unknown"


def _acceptance(status: str, review_approved: bool | None, degraded: bool) -> str:
    if status in SUCCESS_STATUSES and review_approved is not False and not degraded:
        return "accepted"
    if status in FAILED_STATUSES or status in BLOCKED_STATUSES or degraded:
        return "rejected"
    return "unknown"


def _codex_rework_required(outcome: str, degraded: bool, review: dict[str, Any]) -> bool:
    return bool(
        degraded
        or outcome in {"failed", "approval", "degraded"}
        or review.get("required_changes")
        or review.get("blocking_issues")
    )


def _changed_files_count(metrics: list[dict[str, Any]], verify: dict[str, Any], result: dict[str, Any]) -> int:
    for row in metrics:
        value = row.get("changed_files_count")
        if value is not None:
            return _int(value)
    for value in (verify.get("changed_files"), result.get("changed_files")):
        if isinstance(value, list):
            return len(value)
    return 0


def _metric_bool(metrics: list[dict[str, Any]], key: str) -> bool | None:
    for row in metrics:
        if row.get(key) is not None:
            return bool(row.get(key))
    return None


def _metadata_flag(metrics: list[dict[str, Any]], key: str) -> bool:
    for row in metrics:
        metadata = row.get("metadata")
        if isinstance(metadata, dict) and metadata.get(key):
            return True
    return False


def _failure_reason(metrics: list[dict[str, Any]], review: dict[str, Any], result: dict[str, Any]) -> str:
    for row in metrics:
        if row.get("failure_reason"):
            return str(row.get("failure_reason"))
    if review.get("degradation_reason"):
        return str(review.get("degradation_reason"))
    if result.get("degradation_reason"):
        return str(result.get("degradation_reason"))
    return ""


def _classify_goal(goal: str) -> str:
    lowered = goal.lower()
    if any(word in lowered for word in ("只读", "audit", "调查", "分析", "review")):
        return "read_only_analysis"
    if any(word in lowered for word in ("test", "测试")):
        return "test_work"
    if any(word in lowered for word in ("doc", "readme", "文档")):
        return "docs"
    if any(word in lowered for word in ("ui", "页面", "样式", "layout")):
        return "ui"
    return "coding"


def _group_counts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get(key) or "unknown")
        item = grouped.setdefault(name, {"name": name, "total": 0, "success": 0, "rework": 0})
        item["total"] += 1
        if row.get("outcome") == "success":
            item["success"] += 1
        if row.get("codex_rework_required"):
            item["rework"] += 1
    result = []
    for item in grouped.values():
        item["success_rate"] = _pct(int(item["success"]), int(item["total"]))
        item["rework_rate"] = _pct(int(item["rework"]), int(item["total"]))
        result.append(item)
    result.sort(key=lambda item: (-int(item["total"]), str(item["name"])))
    return result


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        if value is not None:
            return bool(value)
    return None


def _truthy_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
