"""Approval Scorer — dynamic risk scoring for tasks.

Computes a risk score (0.0–1.0) based on:
- Task type classification
- File path sensitivity
- Project history
- User's stated risk level
"""

from __future__ import annotations

from typing import Any


def dynamic_risk_score(
    task: dict[str, Any],
    project: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> float:
    """Compute a dynamic risk score for a task.

    Returns a float in [0.0, 1.0] where:
    - 0.0 = trivially safe
    - 0.5 = medium risk
    - 1.0 = maximum risk
    """
    project = project or {}
    user_goal = str(task.get("user_goal", "")).lower()
    risk_level = task.get("risk_level", "medium")
    task_type = task.get("task_type", "routine_coding")

    score = 0.0

    # ── Base score from user-specified risk level ──
    base = {"low": 0.15, "medium": 0.45, "high": 0.75}.get(risk_level, 0.45)
    score = base

    # ── Task type adjustments ──
    task_type_delta = {
        "docs": -0.2,
        "test_generation": -0.2,
        "simple_bugfix": -0.1,
        "routine_coding": 0.0,
        "complex_coding": 0.15,
        "hard_bugfix": 0.2,
        "large_refactor": 0.25,
        "large_context": 0.1,
    }
    score += task_type_delta.get(task_type, 0.0)

    # ── Project stack sensitivity ──
    stack = [str(s).lower() for s in project.get("stack", [])]
    if "android" in stack:
        score += 0.05  # mobile deployments are higher risk
    if any(s in stack for s in ("kubernetes", "terraform", "docker")):
        score += 0.1  # infra changes are riskier

    # ── Forbidden path exposure ──
    forbidden = project.get("forbidden_paths", [])
    if forbidden:
        for fp in forbidden:
            if fp.lower() in user_goal:
                score = min(1.0, score + 0.3)
                break

    # ── History adjustments ──
    if history:
        recent_failures = sum(1 for h in history[-10:] if h.get("status") in ("FAILED", "FAILED_FINAL"))
        if recent_failures >= 2:
            score += 0.1  # recent failures suggest riskier area
        recent_success = sum(1 for h in history[-10:] if h.get("status") in ("DONE", "COMPLETED"))
        if recent_success >= 5:
            score -= 0.05  # reliable project history reduces risk

    return max(0.0, min(1.0, score))
