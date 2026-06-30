from __future__ import annotations

from pathlib import Path
from typing import Any

from .read_only_salvage import (
    ReadOnlySalvagePolicy,
    extract_worker_partial_text as _extract_worker_partial_text,
    extract_worker_success_text as _extract_worker_success_text,
    looks_like_meaningful_read_only_output as _looks_like_meaningful_read_only_output,
    worker_text_candidates as _worker_text_candidates,
)


def extract_worker_success_text(path: Path) -> str | None:
    return _extract_worker_success_text(path)


def extract_worker_partial_text(path: Path) -> str | None:
    return _extract_worker_partial_text(path)


def worker_text_candidates(event: dict[str, Any]) -> list[str]:
    return _worker_text_candidates(event)


def looks_like_meaningful_read_only_output(text: str) -> bool:
    return _looks_like_meaningful_read_only_output(text)


def read_only_result_can_finish(task: dict[str, Any], worker_result: Any) -> bool:
    return (
        not task_requires_diff(task)
        and getattr(worker_result, "status", "") == "success"
        and not getattr(worker_result, "changed_files", [])
    )


def read_only_failure_summary(
    task: dict[str, Any],
    worker_result: Any,
    failure: Any | None,
) -> str | None:
    if task_requires_diff(task) or getattr(worker_result, "changed_files", []):
        return None
    result = ReadOnlySalvagePolicy().salvage(task, worker_result, failure)
    return result.summary if result else None


def read_only_review(task: dict[str, Any], reason: str = "read_only_no_diff") -> dict[str, Any]:
    return {
        "approved": True,
        "review_mode": "skipped_read_only",
        "degraded": False,
        "degradation_reason": None,
        "available": True,
        "risk_level": task.get("risk_level", "medium"),
        "blocking_issues": [],
        "non_blocking_issues": [],
        "required_changes": [],
        "final_recommendation": "read-only task completed with artifacts; no patch or PR is required",
        "can_create_pr": False,
        "reason": reason,
    }


def task_requires_diff(task: dict[str, Any]) -> bool:
    goal = str(task.get("user_goal", "")).lower()
    task_type = str(task.get("task_type", "")).lower()
    if task.get("expected_diff") is not None:
        return bool(task.get("expected_diff"))
    if str(task.get("task_mode") or "").lower() in {"read_only", "audit"}:
        return False
    if task.get("allow_empty_diff") is True:
        return False
    explicit_no_write_markers = (
        "read-only",
        "readonly",
        "no changes",
        "do not modify",
        "do not edit",
        "do not write",
        "do not change files",
        "without modifying",
        "只读",
        "不修改",
        "不要修改",
        "不改",
        "不要改",
        "不写入",
        "不自动改文件",
        "只做只读分析",
    )
    if any(marker in goal for marker in explicit_no_write_markers):
        return False
    read_only_markers = (
        "analyze",
        "analysis",
        "evaluate",
        "assessment",
        "review",
        "inspect",
        "read-only",
        "no changes",
        "do not modify",
        "do not edit",
        "只读",
        "分析",
        "评价",
        "评估",
        "审查",
        "检查",
        "不修改",
        "不要修改",
        "不改",
        "不要改",
        "不写入",
    )
    strong_edit_markers = (
        "fix",
        "implement",
        "refactor",
        "修复",
        "实现",
        "新增",
    )
    if any(marker in goal for marker in read_only_markers) and not any(
        marker in goal for marker in strong_edit_markers
    ):
        return False
    edit_markers = (
        "fix",
        "bug",
        "modify",
        "change",
        "update",
        "edit",
        "add",
        "implement",
        "refactor",
        "修复",
        "修改",
        "更新",
        "实现",
        "新增",
    )
    if any(marker in goal for marker in edit_markers):
        return True
    return task_type in {"simple_bugfix", "routine_coding", "complex_coding", "hard_bugfix", "large_refactor"}


def task_requests_project_verification(task: dict[str, Any]) -> bool:
    goal = str(task.get("user_goal", "")).lower()
    verification_markers = (
        "run tests",
        "run test",
        "run npm test",
        "run npm run check",
        "run pytest",
        "run vitest",
        "run playwright",
        "运行验证",
        "执行验证",
        "跑验证",
        "运行测试",
        "跑测试",
        "执行测试",
    )
    if any(marker in goal for marker in verification_markers):
        return True
    command_only_markers = ("npm test", "npm run check")
    command_reference_markers = (
        "输出",
        "列出",
        "建议",
        "推荐",
        "最小测试命令",
        "test_suggestions",
        "测试命令",
    )
    if any(marker in goal for marker in command_only_markers):
        return not any(marker in goal for marker in command_reference_markers)
    return False


def skip_project_verification_for_read_only_task(task: dict[str, Any], worker_result: Any) -> bool:
    policy = str(task.get("verification_policy") or "").lower()
    if policy in {"none", "changed_files_only"}:
        return not getattr(worker_result, "changed_files", [])
    if policy in {"unit", "full"}:
        return False
    return (
        not task_requires_diff(task)
        and not getattr(worker_result, "changed_files", [])
        and not task_requests_project_verification(task)
    )
