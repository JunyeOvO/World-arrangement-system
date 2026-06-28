"""Dynamic Approval Graph — core decision engine.

Determines the approval mode for a task based on:
- Hard security rules (always BLOCKED)
- User policy overrides (HARD_APPROVAL / SOFT_APPROVAL / AUTO)
- Learned patterns (trust-based auto-approval for low/medium risk)
- Risk level and task type heuristics
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .constants import (
    NON_REVERSIBLE_COMMAND_PATTERNS,
    SENSITIVE_TOPIC_KEYWORDS,
    FORBIDDEN_WRITE_PATHS,
    HARD_APPROVAL_WRITE_PATHS,
    DEFAULT_FORBIDDEN_PATHS,
)


class ApprovalMode(str, Enum):
    AUTO_SILENT = "AUTO_SILENT"
    AUTO_WITH_SUMMARY = "AUTO_WITH_SUMMARY"
    SOFT_APPROVAL = "SOFT_APPROVAL"
    HARD_APPROVAL = "HARD_APPROVAL"
    BLOCKED = "BLOCKED"


@dataclass
class ApprovalDecision:
    mode: ApprovalMode
    reason: str
    risk_score: float = 0.5
    matched_rule: str | None = None
    learned_pattern_id: int | None = None
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_plan: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "risk_score": self.risk_score,
            "matched_rule": self.matched_rule,
            "learned_pattern_id": self.learned_pattern_id,
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "requires_plan": self.requires_plan,
        }


# ── Hard-risk patterns that can NEVER be auto-approved ──
# Category 3: Forbidden write paths → BLOCKED
HARD_RISK_PATHS = set(FORBIDDEN_WRITE_PATHS)

# Category 4: Hard-approval write paths → HARD_APPROVAL
HARD_APPROVAL_PATHS = set(HARD_APPROVAL_WRITE_PATHS)

# Category 1: Non-reversible commands → BLOCKED
HARD_RISK_COMMANDS: list[str] = list(NON_REVERSIBLE_COMMAND_PATTERNS)

# Category 2: Sensitive topic keywords → WARN only (replaces old HARD_RISK_TASK_KEYWORDS)
SENSITIVE_TOPICS: list[str] = list(SENSITIVE_TOPIC_KEYWORDS)


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(p.lower() in t for p in patterns)


def check_hard_risk(
    user_goal: str,
    planned_files: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Evaluate hard risk from task description and planned files.

    Returns (blocking_issues, warnings).

    Phase 3 upgrade:
    - Sensitive topic keywords (auth, payment, ...) → WARN only
    - Non-reversible commands (rm -rf /, git push --force, ...) → BLOCKED
    - Forbidden write paths (.env, secrets/, *.pem, ...) → BLOCKED
    - Hard-approval write paths (infra/prod/, deploy/prod/, ...) → HARD_APPROVAL (in warnings)
    """
    issues: list[str] = []
    warnings: list[str] = []

    # ── Check sensitive topic keywords → WARN only ──
    for kw in SENSITIVE_TOPICS:
        if _keyword_matches_word_boundary(kw, user_goal):
            warnings.append(f"sensitive topic in goal: {kw}")

    # ── Check non-reversible commands → BLOCKED ──
    for pattern in HARD_RISK_COMMANDS:
        if _command_pattern_matches(pattern, user_goal):
            issues.append(f"non-reversible command pattern detected: {pattern}")

    # ── Check file paths ──
    if planned_files:
        for fp in planned_files:
            # Forbidden write paths → BLOCKED
            for forbidden in HARD_RISK_PATHS:
                if _fnmatch(fp, forbidden):
                    issues.append(f"forbidden path write: {forbidden} ({fp})")
            # Hard-approval paths → HARD_APPROVAL signal
            for ha_path in HARD_APPROVAL_PATHS:
                if _fnmatch(fp, ha_path):
                    warnings.append(f"hard-approval path touched: {ha_path} ({fp})")

    return issues, warnings


def _fnmatch(name: str, pattern: str) -> bool:
    """Minimal glob matching for forbidden path checks."""
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


class ApprovalGraph:
    """Main approval decision engine."""

    def __init__(self, db=None):
        self._db = db

    def decide(
        self,
        task: dict[str, Any],
        project: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> ApprovalDecision:
        project = project or {}
        project_id = task.get("project_id", "")
        user_goal = str(task.get("user_goal", ""))
        risk_level = task.get("risk_level", "medium")
        task_type = task.get("task_type", _classify_task_type(user_goal, project))

        # ── 1. Check hard risks ──
        blocking_issues, hard_warnings = check_hard_risk(user_goal)

        # Non-reversible commands / forbidden path writes → BLOCKED
        if blocking_issues:
            return ApprovalDecision(
                ApprovalMode.BLOCKED,
                "hard-risk security rule triggered",
                risk_score=1.0,
                blocking_issues=blocking_issues,
                warnings=hard_warnings,
            )

        # Prod path writes without other blocking issues → HARD_APPROVAL
        touches_hard_approval_paths = any(
            "hard-approval path" in w for w in hard_warnings
        )

        # ── 2. Check policy overrides ──
        if self._db:
            overrides = self._db.get_policy_overrides(project_id)
            for ov in overrides:
                matcher = _parse_json(ov.get("matcher_json", "{}"))
                if _matches_override(user_goal, task_type, matcher):
                    mode = ApprovalMode(ov["approval_mode"])
                    return ApprovalDecision(
                        mode,
                        f"policy override: {ov['rule_name']}",
                        matched_rule=ov["rule_name"],
                    )

        # ── 3. Check learned patterns ──
        if self._db:
            patterns = self._db.get_learned_patterns(project_id, active_only=True)
            for pat in patterns:
                if pat["trust_score"] >= 0.7 and pat["task_type"] == task_type:
                    suggested = pat.get("suggested_mode")
                    if suggested in ("AUTO_SILENT", "AUTO_WITH_SUMMARY"):
                        return ApprovalDecision(
                            ApprovalMode(suggested),
                            f"learned pattern (trust={pat['trust_score']:.2f}, id={pat['id']})",
                            risk_score=max(0.0, 0.3 - pat["trust_score"] * 0.3),
                            learned_pattern_id=pat["id"],
                        )

        # ── 4. Risk-based fallback ──
        if risk_level == "low":
            return ApprovalDecision(
                ApprovalMode.AUTO_WITH_SUMMARY,
                "low risk, auto with summary",
                risk_score=0.2,
                warnings=hard_warnings,
            )
        elif risk_level == "medium":
            return ApprovalDecision(
                ApprovalMode.SOFT_APPROVAL,
                "medium risk, requires soft approval",
                risk_score=0.5,
                requires_plan=task_type in ("complex_coding", "large_refactor"),
                warnings=hard_warnings,
            )
        else:  # high
            if touches_hard_approval_paths:
                return ApprovalDecision(
                    ApprovalMode.HARD_APPROVAL,
                    "high risk with production path access, requires explicit approval",
                    risk_score=0.9,
                    requires_plan=True,
                    warnings=hard_warnings,
                )
            return ApprovalDecision(
                ApprovalMode.SOFT_APPROVAL,
                "high risk but no real danger detected; soft approval with output gating",
                risk_score=0.6,
                requires_plan=True,
                warnings=hard_warnings,
            )

    def explain(self, decision: ApprovalDecision) -> str:
        """Return a human-readable explanation of the decision."""
        lines = [
            f"Approval Mode: {decision.mode.value}",
            f"Risk Score: {decision.risk_score:.2f}",
            f"Reason: {decision.reason}",
        ]
        if decision.matched_rule:
            lines.append(f"Matched Rule: {decision.matched_rule}")
        if decision.learned_pattern_id:
            lines.append(f"Learned Pattern ID: {decision.learned_pattern_id}")
        if decision.blocking_issues:
            lines.append("Blocking Issues:")
            for bi in decision.blocking_issues:
                lines.append(f"  - {bi}")
        if decision.warnings:
            lines.append("Warnings:")
            for w in decision.warnings:
                lines.append(f"  - {w}")
        if decision.requires_plan:
            lines.append("⚠ A detailed plan is required before execution.")
        return "\n".join(lines)


def _classify_task_type(user_goal: str, project: dict[str, Any]) -> str:
    """Classify task type from goal text and project context."""
    g = user_goal.lower()

    if any(kw in g for kw in ["readme", "doc", "文档", "注释", "comment"]):
        return "docs"
    if any(kw in g for kw in ["test", "测试", "unittest", "pytest"]):
        return "test_generation"
    if any(kw in g for kw in ["bug", "fix", "修复", "bugfix", "bug修复"]):
        if any(kw in g for kw in ["complex", "复杂", "crash", "崩溃", "race condition"]):
            return "hard_bugfix"
        return "simple_bugfix"
    if any(kw in g for kw in ["refactor", "重构", "rewrite", "重写"]):
        return "large_refactor"
    if any(kw in g for kw in ["架构", "architecture", "design", "设计"]):
        return "complex_coding"
    if any(kw in g for kw in ["multi-file", "multi file", "多文件"]):
        return "complex_coding"
    if any(kw in g for kw in ["auth", "鉴权", "middleware", "中间件"]):
        return "complex_coding"

    stack = project.get("stack", [])
    stack_str = " ".join(str(s).lower() for s in stack)
    if any(fw in stack_str for fw in ["android", "kotlin", "react", "vue"]):
        return "complex_coding"  # multi-file stack projects default to complex

    return "routine_coding"


def _parse_json(raw: str) -> dict[str, Any]:
    import json
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _matches_override(user_goal: str, task_type: str, matcher: dict[str, Any]) -> bool:
    """Check if a task matches a policy override's matcher criteria."""
    if not matcher:
        return False
    task_type_match = matcher.get("task_type")
    if task_type_match and task_type_match != task_type:
        return False
    keywords = matcher.get("keywords", [])
    if keywords:
        g = user_goal.lower()
        if not any(kw.lower() in g for kw in keywords):
            return False
    return True


def _keyword_matches_word_boundary(keyword: str, text: str) -> bool:
    """Check if keyword appears as a meaningful word in text.

    Uses word-boundary matching to avoid false positives:
    - "prod" matches "deploy to prod" but NOT "update product list"
    - "pay" matches "add payment UI" but NOT "repay loan"
    - "auth" matches "fix auth bug" but NOT "unauthorized" (auth is embedded)

    For CJK characters, uses direct substring (no word boundaries in CJK).
    """
    import re

    lower = text.lower()
    kw = keyword.lower()

    # CJK keywords: direct substring
    if any("一" <= c <= "鿿" or "぀" <= c <= "ヿ" for c in kw):
        return kw in lower

    # Multi-word keywords: join with optional whitespace
    normalized_kw = kw.replace(" ", r"\s+")
    # Word boundary match
    pattern = r"(?<![a-z])" + normalized_kw + r"(?![a-z])"
    return bool(re.search(pattern, lower))


def _command_pattern_matches(pattern: str, text: str) -> bool:
    """Match a non-reversible command pattern against text.

    For patterns with wildcards like 'curl * | sh', converts * to .* for regex.
    Otherwise uses exact substring matching.
    """
    import re

    if "*" in pattern:
        regex = re.escape(pattern).replace(r"\*", ".*")
        return bool(re.search(regex, text.lower()))
    return pattern.lower() in text.lower()
