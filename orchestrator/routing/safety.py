"""SafetyGate: security check before candidate routing."""
from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

from .schema import SafetyResult, TaskFeatures, TaskLabels


_BLOCKED_PATHS = [
    ".env", ".env.*", "secrets/**", "keys/**", "credentials/**",
    "*.pem", "*.key", "*.pfx",
]

_BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "git push --force", "gh pr merge",
    "drop database", "truncate", "chmod -R 777 /", "curl | sh", "wget | sh",
]

_HARD_APPROVAL_PATTERNS = [
    "prod", "deploy/prod", "infra/prod", "database/migrations/prod",
]


def safety_gate(
    task: dict[str, Any],
    project: dict[str, Any] | None,
    features: TaskFeatures,
    labels: TaskLabels,
) -> SafetyResult:
    """Run safety checks before candidate routing.

    Returns SafetyResult. If blocked, routing must stop.
    """
    goal_lower = features.goal_lower
    target_paths = features.target_paths
    blocked_paths: list[str] = []

    # Check blocked paths in target
    for path_pattern in _BLOCKED_PATHS:
        for tp in target_paths:
            if _path_matches(tp.lower(), path_pattern.lower()):
                blocked_paths.append(tp)
        if _mentions_blocked_path_as_target(goal_lower, path_pattern):
            blocked_paths.append(path_pattern)

    if blocked_paths:
        return SafetyResult(
            allowed=False,
            blocked=True,
            reason=f"Blocked paths in target: {blocked_paths}",
            blocked_paths=blocked_paths,
        )

    # Check blocked commands in goal
    for cmd in _BLOCKED_COMMANDS:
        if cmd.lower() in goal_lower:
            return SafetyResult(
                allowed=False,
                blocked=True,
                reason=f"Blocked command in goal: {cmd}",
            )

    # Check hard approval patterns
    for pattern in _HARD_APPROVAL_PATTERNS:
        for tp in target_paths:
            if pattern.lower() in tp.lower():
                return SafetyResult(
                    allowed=True,
                    blocked=False,
                    requires_hard_approval=True,
                    reason=f"Production path requires hard approval: {tp}",
                )
        if pattern.lower() in goal_lower:
            # Only trigger if action is modify/refactor, not docs/analyze
            if labels.needs_code_change and not _is_docs_context(features, labels):
                return SafetyResult(
                    allowed=True,
                    blocked=False,
                    requires_hard_approval=True,
                    reason=f"Production context requires hard approval: {pattern}",
                )

    return SafetyResult(allowed=True)


def _path_matches(target: str, pattern: str) -> bool:
    """Simple glob matching for path patterns."""
    if fnmatch(target, pattern):
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return target.startswith(prefix) or target == prefix.rstrip("/")
    if pattern.startswith("*."):
        ext = pattern[1:]
        return target.endswith(ext)
    return target == pattern


def _mentions_blocked_path_as_target(goal_lower: str, pattern: str) -> bool:
    """Return True only for direct target-like mentions of a blocked path.

    Safety prompts often say "do not modify .env". Treat those as constraints
    for workers, not as evidence that the task target is .env.
    """
    needle = pattern.lower().rstrip("*")
    index = goal_lower.find(needle)
    if index < 0:
        return False

    clause_start = max(goal_lower.rfind(sep, 0, index) for sep in (".", ";", "\n"))
    clause = goal_lower[clause_start + 1 : index + len(needle)]

    negative_markers = (
        "do not",
        "don't",
        "dont",
        "must not",
        "never",
        "without modifying",
        "不要",
        "不得",
        "禁止",
        "不修改",
    )
    if any(marker in clause for marker in negative_markers):
        return False

    target_verbs = (
        "edit",
        "modify",
        "change",
        "update",
        "write",
        "create",
        "add",
        "delete",
        "remove",
        "fix",
        "touch",
        "生成",
        "编辑",
        "修改",
        "更新",
        "写入",
        "创建",
        "删除",
        "修复",
    )
    return any(verb in clause for verb in target_verbs)


def _is_docs_context(features: TaskFeatures, labels: TaskLabels) -> bool:
    """Check if task is purely documentation (no code change)."""
    return (
        "docs" in features.actions
        or "docs" in features.path_kinds
        or labels.artifact_type == "docs"
    ) and not labels.needs_code_change
