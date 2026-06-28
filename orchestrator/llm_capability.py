from __future__ import annotations

from typing import Any


CAPABILITY_TIERS = {"default", "high", "max"}

TOP_CONTEXT_STANDARD: dict[str, Any] = {
    "context_policy": "top",
    "context_budget": "max_available",
    "prompt_budget": "max_available",
    "tool_budget": "max_safe",
    "evidence_budget": "max_safe",
}

_MODEL_TIER_SETTINGS: dict[str, dict[str, dict[str, Any]]] = {
    "deepseek_flash": {
        "default": {"effort": "low"},
        "high": {"effort": "medium"},
        "max": {"effort": "high"},
    },
    "deepseek_pro": {
        "default": {"effort": "medium"},
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    },
    "mimo_v25": {
        "default": {"effort": "medium"},
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    },
    "mimo_v25_pro": {
        "default": {"effort": "high"},
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    },
    "opencode-go/glm-5.2": {
        "default": {"effort": "medium", "variant": None},
        "high": {"effort": "high", "variant": "high"},
        "max": {"effort": "max", "variant": "max"},
    },
    "opencode_go_glm52": {
        "default": {"effort": "medium", "variant": None},
        "high": {"effort": "high", "variant": "high"},
        "max": {"effort": "max", "variant": "max"},
    },
    "codex_reviewer": {
        "default": {"effort": "high"},
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    },
}


def normalize_capability_tier(value: str | None, intensity: str | None = None) -> str:
    raw = (value or "").strip().lower()
    if raw in CAPABILITY_TIERS:
        return raw
    level = (intensity or "").strip().lower()
    if level == "max":
        return "max"
    if level == "high":
        return "high"
    return "default"


def capability_profile(model: str, tier: str | None = None, intensity: str | None = None) -> dict[str, Any]:
    normalized_tier = normalize_capability_tier(tier, intensity)
    model_settings = _MODEL_TIER_SETTINGS.get(model, {})
    tier_settings = dict(model_settings.get(normalized_tier) or model_settings.get("default") or {})
    return {
        "tier": normalized_tier,
        **TOP_CONTEXT_STANDARD,
        **tier_settings,
    }


def env_for_capability(profile: dict[str, Any]) -> dict[str, str]:
    env = {
        "AI_ORCHESTRATOR_CAPABILITY_TIER": str(profile.get("tier", "default")),
        "AI_ORCHESTRATOR_CONTEXT_POLICY": str(profile.get("context_policy", "top")),
        "AI_ORCHESTRATOR_CONTEXT_BUDGET": str(profile.get("context_budget", "max_available")),
        "AI_ORCHESTRATOR_PROMPT_BUDGET": str(profile.get("prompt_budget", "max_available")),
        "CLAUDE_CODE_EFFORT_LEVEL": str(profile.get("effort", "medium")),
    }
    return env
