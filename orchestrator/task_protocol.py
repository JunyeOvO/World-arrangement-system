from __future__ import annotations

import re
from typing import Any


TASK_MODES = {"read_only", "patch", "test", "docs", "audit"}
VERIFICATION_POLICIES = {"none", "changed_files_only", "unit", "full"}
READ_BUDGET_PROFILES = {
    "quick_triage": {
        "max_files": 6,
        "max_dirs": 2,
        "max_worker_turns": 6,
        "max_duration_sec": 90,
        "max_output_tokens": 2500,
    },
    "code_contract_audit": {
        "max_files": 10,
        "max_dirs": 4,
        "max_worker_turns": 10,
        "max_duration_sec": 150,
        "max_output_tokens": 4000,
    },
    "next_task_planning": {
        "max_files": 14,
        "max_dirs": 5,
        "max_worker_turns": 14,
        "max_duration_sec": 210,
        "max_output_tokens": 4500,
    },
    "docs_review": {
        "max_files": 6,
        "max_dirs": 2,
        "max_worker_turns": 6,
        "max_duration_sec": 90,
        "max_output_tokens": 3000,
    },
}
READ_BUDGET_FIELDS = {
    "max_files": 8,
    "max_dirs": 3,
    "max_worker_turns": 8,
    "max_duration_sec": 900,
    "max_output_tokens": 4000,
}


def normalize_task_protocol(
    user_goal: str,
    *,
    task_mode: str | None = None,
    expected_diff: bool | None = None,
    verification_policy: str | None = None,
    read_budget_profile: str | None = None,
    read_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frontmatter = parse_task_protocol_frontmatter(user_goal)
    mode = _normalize_choice(
        task_mode or frontmatter.get("task_mode"),
        TASK_MODES,
        _infer_task_mode(user_goal),
    )
    diff = _normalize_bool(
        expected_diff if expected_diff is not None else frontmatter.get("expected_diff"),
        default=mode not in {"read_only", "audit"},
    )
    policy = _normalize_choice(
        verification_policy or frontmatter.get("verification_policy"),
        VERIFICATION_POLICIES,
        _default_verification_policy(mode, diff),
    )
    profile = normalize_read_budget_profile(
        read_budget_profile or frontmatter.get("read_budget_profile"),
        default=_default_read_budget_profile(mode, user_goal),
    )
    budget = normalize_read_budget(
        {
            **READ_BUDGET_PROFILES.get(profile, {}),
            **_frontmatter_budget(frontmatter),
            **(read_budget or {}),
        }
    )
    return {
        "task_mode": mode,
        "expected_diff": diff,
        "verification_policy": policy,
        "read_budget_profile": profile,
        "read_budget": budget,
    }


def parse_task_protocol_frontmatter(user_goal: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    budget: dict[str, Any] = {}
    for raw_line in str(user_goal or "").splitlines()[:24]:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        normalized_key = key.lower().replace("-", "_")
        if normalized_key.startswith("read_budget."):
            budget[normalized_key.split(".", 1)[1]] = value
        elif normalized_key in {"task_mode", "expected_diff", "verification_policy", "read_budget_profile"}:
            fields[normalized_key] = value
    if budget:
        fields["read_budget"] = budget
    return fields


def normalize_read_budget(value: dict[str, Any] | None = None) -> dict[str, int]:
    raw = value or {}
    budget: dict[str, int] = {}
    for key, default in READ_BUDGET_FIELDS.items():
        budget[key] = _positive_int(raw.get(key), default)
    return budget


def normalize_read_budget_profile(value: Any, default: str = "quick_triage") -> str:
    candidate = str(value or "").strip().lower().replace("-", "_")
    if candidate in READ_BUDGET_PROFILES:
        return candidate
    fallback = str(default or "quick_triage").strip().lower().replace("-", "_")
    return fallback if fallback in READ_BUDGET_PROFILES else "quick_triage"


def verification_commands_for_policy(
    policy: str,
    test_commands: list[str],
    build_commands: list[str],
) -> tuple[list[str], list[str]]:
    normalized = _normalize_choice(policy, VERIFICATION_POLICIES, "full")
    if normalized in {"none", "changed_files_only"}:
        return [], []
    if normalized == "unit":
        return list(test_commands[:1]), []
    return list(test_commands), list(build_commands)


def apply_read_budget_to_route(route: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    budget = normalize_read_budget(task.get("read_budget"))
    updated = dict(route)
    if "max_turns" not in updated:
        updated["max_turns"] = budget["max_worker_turns"]
    if "timeout_sec" not in updated:
        updated["timeout_sec"] = budget["max_duration_sec"]
    return updated


def _frontmatter_budget(fields: dict[str, Any]) -> dict[str, Any]:
    value = fields.get("read_budget")
    return value if isinstance(value, dict) else {}


def _default_verification_policy(task_mode: str, expected_diff: bool) -> str:
    if task_mode == "test":
        return "unit"
    if task_mode in {"read_only", "audit"} or not expected_diff:
        return "changed_files_only"
    return "full"


def _default_read_budget_profile(task_mode: str, user_goal: str) -> str:
    goal = str(user_goal or "").lower()
    if task_mode == "docs" or any(marker in goal for marker in ("readme", "文档", "onboarding")):
        return "docs_review"
    if any(marker in goal for marker in ("contract", "数据契约", "workarea", "3d", "架构", "architecture")):
        return "code_contract_audit"
    if any(marker in goal for marker in ("next task", "下一轮", "下一步", "候选任务", "task candidates")):
        return "next_task_planning"
    return "quick_triage"


def _infer_task_mode(user_goal: str) -> str:
    goal = str(user_goal or "").lower()
    if any(marker in goal for marker in ("只读", "read-only", "read only", "audit", "调查", "评估", "分析")):
        return "read_only"
    if any(marker in goal for marker in ("readme", "doc", "文档")):
        return "docs"
    if any(marker in goal for marker in ("test", "测试", "验证")):
        return "test"
    return "patch"


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    candidate = str(value or "").strip().lower().replace("-", "_")
    return candidate if candidate in allowed else default


def _normalize_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
