from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable

from .constants import (
    DEFAULT_FORBIDDEN_PATHS,
    NON_REVERSIBLE_COMMAND_PATTERNS,
    SENSITIVE_TOPIC_KEYWORDS,
)


@dataclass
class RiskResult:
    allowed: bool
    risk_level: str
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def evaluate_task(
    user_goal: str,
    risk_level: str = "medium",
    auto_pr: bool = False,
    auto_merge: bool = False,
) -> RiskResult:
    """Evaluate task safety from the user's intent description.

    Design (Phase 2 upgrade):
    - Non-reversible commands (rm -rf /, git push --force, ...) → issues (BLOCKED)
    - Sensitive topic keywords (auth, payment, deploy, ...) → warnings ONLY
    - auto_merge is always forbidden in V1
    """
    issues: list[str] = []
    warnings: list[str] = []
    lower = user_goal.lower()

    if auto_merge:
        issues.append("auto_merge is forbidden in V1")

    # ── Non-reversible commands → BLOCKED ──
    for pattern in NON_REVERSIBLE_COMMAND_PATTERNS:
        if _command_pattern_matches(pattern, lower):
            issues.append(f"task mentions non-reversible command: {pattern}")

    # ── Sensitive topic keywords → WARN only ──
    for keyword in SENSITIVE_TOPIC_KEYWORDS:
        if _keyword_matches_contextually(keyword, user_goal):
            warnings.append(f"sensitive topic: {keyword}")

    if risk_level == "high" and auto_pr:
        warnings.append("high-risk tasks should normally set auto_pr=false")

    return RiskResult(not issues, risk_level, issues, warnings)


def scan_command(command: str) -> RiskResult:
    normalized = " ".join(shlex.split(command, posix=False)).lower()
    issues: list[str] = []
    for p in NON_REVERSIBLE_COMMAND_PATTERNS:
        if _command_pattern_matches(p, normalized):
            issues.append(f"non-reversible command pattern: {p}")
    return RiskResult(not issues, "high" if issues else "low", issues, [])


def check_changed_files(
    changed_files: Iterable[str],
    forbidden_paths: Iterable[str] | None = None,
) -> RiskResult:
    patterns = list(forbidden_paths or DEFAULT_FORBIDDEN_PATHS)
    issues: list[str] = []
    for file_name in changed_files:
        posix = PurePosixPath(file_name.replace("\\", "/")).as_posix()
        if any(_matches(posix, pattern) for pattern in patterns):
            issues.append(f"forbidden path changed: {posix}")
    return RiskResult(not issues, "high" if issues else "low", issues, [])


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"**/{pattern}")


def _command_pattern_matches(pattern: str, text: str) -> bool:
    """Match a non-reversible command pattern against task text.

    Uses exact substring matching for dangerous command patterns.
    For patterns with wildcards like 'curl * | sh', converts * to .* for regex.
    """
    if "*" in pattern:
        regex = re.escape(pattern).replace(r"\*", ".*")
        return bool(re.search(regex, text))
    return pattern.lower() in text


def _keyword_matches_contextually(keyword: str, text: str) -> bool:
    """Check if a sensitive keyword appears as a meaningful word in the text.

    Uses word-boundary matching to avoid false positives:
    - "prod" matches "deploy to prod" but NOT "update product list"
    - "pay" matches "add payment UI" but NOT "repay loan"
    - "auth" matches "fix auth bug" but NOT "unauthorized error" (auth is still a topic word)

    For CJK characters, uses direct substring (no word boundaries in CJK).
    """
    lower = text.lower()
    kw = keyword.lower()

    # CJK keywords: direct substring (characters don't have word boundaries)
    if any("一" <= c <= "鿿" or "぀" <= c <= "ゟ" or "゠" <= c <= "ヿ"
           for c in kw):
        return kw in lower

    # Normalize multi-word keywords
    normalized_kw = kw.replace(" ", r"\s+")
    # Word boundary match: keyword must appear as a distinct word/phrase
    pattern = r"(?<![a-z])" + normalized_kw + r"(?![a-z])"
    return bool(re.search(pattern, lower))

