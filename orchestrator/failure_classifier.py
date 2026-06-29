from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FailureClassification:
    failure_reason: str
    retryable: bool
    recommended_action: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_worker_failure(
    *,
    status: str,
    summary: str = "",
    risks: list[str] | None = None,
    changed_files: list[str] | None = None,
    stdout_path: str | None = None,
    stderr_path: str | None = None,
) -> FailureClassification:
    evidence: list[str] = []
    risks = risks or []
    changed_files = changed_files or []
    text = " ".join([status, summary, *risks, _read(stderr_path)]).lower()
    stream = _read_jsonl(stdout_path)
    subtype = _last_string(stream, "subtype") or _last_string(stream, "error")
    if subtype:
        evidence.append(f"result.subtype={subtype}")
    if changed_files:
        evidence.append(f"changed_files={len(changed_files)}")
    else:
        evidence.append("changed_files=[]")

    if status in {"blocked", "forbidden_path"} or "forbidden path" in text:
        return FailureClassification("forbidden_path", False, "block_and_surface_policy_violation", evidence)
    if status == "cancelled" or "cancelled" in text:
        return FailureClassification("cancelled", False, "stop_without_retry", evidence)
    if _contains_any(text, ["auth", "unauthorized", "invalid api key", "401", "403"]):
        return FailureClassification("auth_failed", False, "stop_and_fix_provider_config", evidence)
    if _contains_any(text, ["not recognized", "not found", "command_missing", "cli unavailable", "program not found"]):
        return FailureClassification("command_missing", False, "stop_and_fix_worker_command", evidence)
    if subtype == "error_max_turns" or "maximum number of turns" in text or "max_turns" in text:
        if changed_files:
            return FailureClassification("max_turns_with_diff", True, "verify_partial_patch", evidence)
        return FailureClassification("max_turns_no_diff", True, "escalate_model_or_narrow_task", evidence)
    if "worker_no_diff" in text or (status == "failed" and not changed_files):
        return FailureClassification("worker_no_diff", True, "retry_with_stronger_route", evidence)
    if status in {"failed", "worker_failed"}:
        return FailureClassification("worker_failed", True, "retry_or_escalate", evidence)
    return FailureClassification(status or "unknown_failure", False, "needs_user_review", evidence)


def classify_verify_failure(
    *,
    tests_passed: bool,
    build_passed: bool,
    forbidden_allowed: bool,
    command_permissions_allowed: bool = True,
    evidence: list[str] | None = None,
) -> FailureClassification:
    evidence = evidence or []
    if not command_permissions_allowed:
        return FailureClassification("dangerous_command", False, "block_and_surface_policy_violation", evidence)
    if not forbidden_allowed:
        return FailureClassification("forbidden_path", False, "block_and_surface_policy_violation", evidence)
    if not build_passed:
        return FailureClassification("build_failed", True, "route_to_repair_or_stop", evidence)
    if not tests_passed:
        return FailureClassification("tests_failed", True, "route_to_repair_or_stop", evidence)
    return FailureClassification("verify_failed", False, "needs_user_review", evidence)


def classify_review_failure(review: dict[str, Any]) -> FailureClassification:
    evidence = [f"{key}={value}" for key, value in review.items() if key in {"approved", "can_create_pr", "error"}]
    if review.get("error") or review.get("available") is False:
        return FailureClassification("review_unavailable", False, "needs_user_review", evidence)
    return FailureClassification("review_rejected", False, "needs_user_review", evidence)


def _read(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return ""


def _read_jsonl(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _last_string(rows: list[dict[str, Any]], key: str) -> str | None:
    for row in reversed(rows):
        value = row.get(key)
        if isinstance(value, str):
            return value
        result = row.get("result")
        if isinstance(result, dict) and isinstance(result.get(key), str):
            return result[key]
    return None


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
