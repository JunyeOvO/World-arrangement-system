"""PolicyOverride: apply project config and history-based policy overrides."""
from __future__ import annotations

from typing import Any

from .schema import CandidateRoute
from ..llm_capability import capability_profile, normalize_capability_tier


def apply_policy_overrides(
    resolved: CandidateRoute,
    task: dict[str, Any],
    project: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
) -> CandidateRoute:
    """Apply project configuration and historical success overrides.

    Merge order (lowest → highest):
    1. Model defaults
    2. History success rate
    3. Project configuration
    4. Strong task rules
    5. Safety gate
    6. Explicit user requirements
    """
    project = project or {}

    # ── Project defaults ──
    if project.get("default_worker") and not resolved.reasons:
        # Only apply if project explicitly configures a different worker
        pass  # CandidateScorer already accounts for project preferences

    # ── Prefer low cost for docs if project says so ──
    if project.get("prefer_low_cost_for_docs") and resolved.model == "deepseek_pro":
        task_goal = str(task.get("user_goal", "")).lower()
        if "readme" in task_goal or "文档" in task_goal or "doc" in task_goal:
            resolved.model = "deepseek_flash"
            resolved.intensity = "low"
            resolved.reasons.append("project prefer_low_cost_for_docs -> downgrade to flash")

    # ── History success rate ──
    if history and isinstance(history, list):
        # Boost confidence if same worker+model has recent successes
        recent_successes = sum(
            1 for h in history[-10:]
            if h.get("status") == "success"
            and h.get("worker") == resolved.worker
            and h.get("model") == resolved.model
        )
        if recent_successes > 0:
            resolved.score += min(recent_successes * 5, 20)
            resolved.reasons.append(f"history: {recent_successes} recent successes for {resolved.worker}/{resolved.model}")

    return resolved


def build_retry_chain(
    resolved: CandidateRoute,
    task: dict[str, Any],
    project: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build retry chain for the selected route.

    ClaudeCodeWorker failure → OpenCodeWorker high → OpenCodeWorker max.
    """
    primary_tier = normalize_capability_tier(None, resolved.intensity)
    chain = [{
        "worker": resolved.worker,
        "model": resolved.model,
        "intensity": resolved.intensity,
        "variant": resolved.variant,
        "capability_tier": primary_tier,
        "capability_profile": capability_profile(resolved.model, primary_tier, resolved.intensity),
    }]

    if resolved.worker == "claude_code":
        # Escalate to OpenCode high on failure
        chain.append({
            "worker": "opencode",
            "model": "opencode-go/glm-5.2",
            "variant": "high",
            "intensity": "high",
            "capability_tier": "high",
            "capability_profile": capability_profile("opencode-go/glm-5.2", "high", "high"),
            "condition": "on_failure",
        })
        # Escalate to OpenCode max on second failure
        chain.append({
            "worker": "opencode",
            "model": "opencode-go/glm-5.2",
            "variant": "max",
            "intensity": "max",
            "capability_tier": "max",
            "capability_profile": capability_profile("opencode-go/glm-5.2", "max", "max"),
            "condition": "on_second_failure",
        })
    elif resolved.worker == "opencode":
        # Already on OpenCode, escalate variant
        if resolved.variant == "high":
            chain.append({
                "worker": "opencode",
                "model": "opencode-go/glm-5.2",
                "variant": "max",
                "intensity": "max",
                "capability_tier": "max",
                "capability_profile": capability_profile("opencode-go/glm-5.2", "max", "max"),
                "condition": "on_failure",
            })
    return chain
