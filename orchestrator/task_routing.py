from __future__ import annotations

from typing import Any

from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier


def world_enabled(project: dict[str, Any]) -> bool:
    world = project.get("world")
    if isinstance(world, dict) and world.get("enabled") is True:
        return True
    return project.get("world_enabled") is True


def world_write_policy(project: dict[str, Any]) -> str:
    world = project.get("world")
    if isinstance(world, dict) and world.get("write_policy"):
        return str(world["write_policy"])
    return str(project.get("world_write_policy") or "zero_write")


def apply_route_override(route: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    override = task.get("route_override")
    if not isinstance(override, dict):
        return route

    worker = override.get("worker") or route.get("selected_worker")
    model = override.get("model") or route.get("selected_model")
    variant = override.get("variant") if override.get("variant") is not None else route.get("variant")
    tier = normalize_capability_tier(variant, route.get("intensity"))
    profile = capability_profile(model, tier, route.get("intensity"))
    if worker == "opencode" and variant in {"high", "max"}:
        profile = capability_profile(model, variant, variant)

    route.update(
        {
            "selected_worker": worker,
            "selected_agent": worker,
            "selected_model": model,
            "selected_llm": model,
            "agent_llm": agent_llm_name(worker, model),
            "variant": variant,
            "capability_tier": profile.get("tier", tier),
            "capability_profile": profile,
            "reason": f"route override: worker={worker}, model={model}, variant={variant}",
            "fallback_models": [],
            "max_retries": 0,
            "escalation_policy": "none",
            "blocked": False,
            "retry_chain": [
                {
                    "worker": worker,
                    "model": model,
                    "variant": variant,
                    "intensity": profile.get("effort") or route.get("intensity"),
                    "capability_tier": profile.get("tier", tier),
                    "capability_profile": profile,
                    "reason": "route override primary attempt",
                }
            ],
        }
    )
    return route
