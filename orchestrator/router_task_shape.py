from __future__ import annotations

import re
from typing import Any


TASK_SHAPES = {
    "targeted_patch",
    "open_bug_hunt",
    "docs_update",
    "test_generation",
    "large_refactor",
    "multimodal_analysis",
    "multimodal_to_code",
    "config_repair",
    "review_only",
}

READ_ONLY_TASK_SHAPES = {
    "review_only",
    "multimodal_analysis",
}


def classify_task_shape(task: dict[str, Any], features: Any | None = None, labels: Any | None = None) -> str:
    explicit = str(task.get("task_shape") or "").strip()
    read_only = is_read_only_task(task)
    if explicit in TASK_SHAPES:
        if read_only and explicit not in READ_ONLY_TASK_SHAPES:
            return "review_only"
        return explicit

    goal = str(task.get("user_goal", ""))
    lower = goal.lower()
    target_paths = [str(p).lower() for p in task.get("target_paths", [])]
    task_type = str(task.get("task_type", "")).lower()
    requires_multimodal = bool(getattr(features, "requires_multimodal", False))
    needs_code_change = bool(getattr(labels, "needs_code_change", False))

    if read_only:
        return "multimodal_analysis" if requires_multimodal else "review_only"
    if requires_multimodal and needs_code_change:
        return "multimodal_to_code"
    if requires_multimodal:
        return "multimodal_analysis"
    if task_type == "hard_bugfix":
        return "large_refactor"
    if task_type in {"large_refactor", "large_context"} or _has_phrase(
        lower,
        ["large refactor", "大规模重构", "重构整个", "rewrite entire"],
    ):
        return "large_refactor"
    if _is_review_only(lower):
        return "review_only"
    if _is_config_repair(lower, target_paths):
        return "config_repair"
    if _is_test_generation(lower):
        return "test_generation"
    if _is_docs_update(lower, target_paths):
        return "docs_update"
    if _is_open_bug_hunt(lower, task):
        return "open_bug_hunt"
    if _is_targeted_patch(lower, target_paths, task_type):
        return "targeted_patch"
    if needs_code_change:
        return "targeted_patch"
    return "review_only" if "analyze" in lower or "分析" in lower else "targeted_patch"


def is_read_only_task(task: dict[str, Any]) -> bool:
    mode = str(task.get("task_mode") or "").strip().lower()
    if mode in {"read_only", "readonly", "audit", "analysis"}:
        return True
    if task.get("expected_diff") is False:
        return True
    verification_policy = str(task.get("verification_policy") or "").strip().lower()
    return verification_policy == "none" and mode == "read_only"


def _is_docs_update(lower: str, target_paths: list[str]) -> bool:
    if any(p.endswith((".md", ".markdown")) or p == "readme.md" or p.startswith("docs/") for p in target_paths):
        return True
    return _has_phrase(lower, ["readme", "markdown", "文档", "documentation", "docs update", "update docs"])


def _is_test_generation(lower: str) -> bool:
    if _has_phrase(
        lower,
        ["test run", "test runs", "tests run", "pytest run", "run tests", "test failure", "tests failed"],
    ):
        return False
    return bool(re.search(r"\b(add|write|create|generate|新增|编写|添加)\s+.*\b(unit\s+)?tests?\b", lower)) or _has_phrase(
        lower,
        ["测试生成", "生成测试", "补测试"],
    )


def _is_open_bug_hunt(lower: str, task: dict[str, Any]) -> bool:
    if task.get("target_paths"):
        return False
    phrases = [
        "find one bug and fix",
        "find a bug and fix",
        "find bug",
        "hunt bug",
        "open bug",
        "找一个 bug",
        "找一个bug",
        "查找 bug",
        "找 bug 并修复",
    ]
    return _has_phrase(lower, phrases)


def _is_targeted_patch(lower: str, target_paths: list[str], task_type: str) -> bool:
    if target_paths:
        return True
    if task_type in {"simple_bugfix", "routine_coding"}:
        return True
    return _has_phrase(lower, ["fix", "修复", "修改", "update", "change", "implement", "新增", "实现"])


def _is_config_repair(lower: str, target_paths: list[str]) -> bool:
    if any(p.endswith((".yaml", ".yml", ".toml", ".json", ".ini")) or "config" in p for p in target_paths):
        return True
    return _has_phrase(lower, ["config", "configuration", "配置", "settings"])


def _is_review_only(lower: str) -> bool:
    return _has_phrase(lower, ["review only", "audit only", "analyze only", "只分析", "只审查", "不要修改"])


def _has_phrase(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)
