from __future__ import annotations

from typing import Any

from .llm_capability import capability_profile, normalize_capability_tier
from .router_history import choose_claude_model


def select_for_shape(
    task_shape: str,
    route: dict[str, Any],
    task: dict[str, Any],
    project: dict[str, Any],
    history: dict[str, Any],
    budget_cap: float | None,
) -> dict[str, Any] | None:
    if route.get("blocked"):
        return None

    explicit_model = str(task.get("force_model") or route.get("selected_model") or "").lower()
    goal = str(task.get("user_goal", "")).lower()
    task_type = str(task.get("task_type", "")).lower()
    if task_type == "hard_bugfix":
        return opencode_route("max")
    if route.get("selected_worker") == "opencode" or project.get("default_worker") == "opencode":
        if project.get("default_worker") == "opencode" and task_type not in {"complex_coding"} and "glm" not in goal:
            variant = normalize_variant(project.get("default_variant"))
        else:
            variant = normalize_variant(route.get("variant"))
            if not variant and route.get("selected_model") == "opencode-go/glm-5.2":
                variant = normalize_variant(project.get("default_variant"))
        return opencode_route(variant) if variant else opencode_route_without_variant()
    if "glm" in explicit_model or "glm" in goal:
        return opencode_route("high")

    if task_shape == "docs_update":
        model = choose_claude_model(
            history,
            ["deepseek_flash", "deepseek_pro"],
            default="deepseek_flash" if route.get("selected_model") == "deepseek_flash" else "deepseek_pro",
            budget_cap=budget_cap,
            allow_low_cost=True,
        )
        return claude_route(model, "low" if model == "deepseek_flash" else "medium")
    if task_shape == "open_bug_hunt":
        return claude_route("deepseek_pro", "high")
    if task_shape == "targeted_patch":
        if single_file_target(task):
            target_model = choose_claude_model(
                history,
                ["deepseek_flash", "deepseek_pro"],
                default="deepseek_pro",
                budget_cap=budget_cap,
                allow_low_cost=True,
            )
        else:
            target_model = "deepseek_pro"
        return claude_route(target_model, "medium" if target_model == "deepseek_pro" else "low")
    if task_shape == "test_generation":
        return claude_route("deepseek_pro", "medium")
    if task_shape == "large_refactor":
        return opencode_route("max")
    if task_shape == "multimodal_analysis":
        return claude_route("mimo_v25", "medium")
    if task_shape == "multimodal_to_code":
        return claude_route("mimo_v25_pro", "high")
    if task_shape == "config_repair":
        return claude_route("deepseek_pro", "medium")
    if task_shape == "review_only":
        return claude_route("deepseek_pro", "medium")
    return None


def retry_chain_for_shape(task_shape: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    primary = route_step(
        str(route.get("selected_worker") or "claude_code"),
        str(route.get("selected_model") or "deepseek_pro"),
        route.get("variant"),
        str(route.get("intensity") or "medium"),
        "primary task_shape route",
    )
    if task_shape == "docs_update":
        fallback = "deepseek_pro" if primary["model"] == "deepseek_flash" else "deepseek_flash"
        return [primary, route_step("claude_code", fallback, None, "medium", "docs_update fallback")]
    if task_shape == "targeted_patch":
        chain = [primary]
        if primary["model"] != "deepseek_pro":
            chain.append(route_step("claude_code", "deepseek_pro", None, "medium", "targeted_patch stronger fallback"))
        chain.append(route_step("opencode", "opencode-go/glm-5.2", "high", "high", "targeted_patch opencode fallback"))
        return chain
    if task_shape in {"open_bug_hunt", "test_generation", "config_repair", "multimodal_to_code"}:
        return [primary, route_step("opencode", "opencode-go/glm-5.2", "high", "high", f"{task_shape} fallback")]
    if task_shape == "large_refactor":
        if primary["worker"] == "opencode" and primary.get("variant") == "max":
            return [
                primary,
                route_step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor high fallback"),
            ]
        return [primary, route_step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor fallback")]
    if task_shape == "multimodal_analysis":
        return [primary, route_step("claude_code", "mimo_v25_pro", None, "high", "multimodal_analysis pro fallback")]
    return [primary]


def fallback_models(chain: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for step in chain[1:]:
        model = str(step.get("model", ""))
        if model and model not in seen:
            seen.append(model)
    return seen


def claude_route(model: str, intensity: str) -> dict[str, Any]:
    tier = normalize_capability_tier(None, intensity)
    return {
        "selected_worker": "claude_code",
        "selected_agent": "claude_code",
        "selected_model": model,
        "selected_llm": model,
        "intensity": intensity,
        "variant": None,
        "capability_tier": tier,
        "capability_profile": capability_profile(model, tier, intensity),
    }


def opencode_route(variant: str) -> dict[str, Any]:
    return {
        "selected_worker": "opencode",
        "selected_agent": "opencode",
        "selected_model": "opencode-go/glm-5.2",
        "selected_llm": "opencode-go/glm-5.2",
        "intensity": variant,
        "variant": variant,
        "capability_tier": variant,
        "capability_profile": capability_profile("opencode-go/glm-5.2", variant, variant),
    }


def opencode_route_without_variant() -> dict[str, Any]:
    tier = normalize_capability_tier(None, "medium")
    return {
        "selected_worker": "opencode",
        "selected_agent": "opencode",
        "selected_model": "opencode-go/glm-5.2",
        "selected_llm": "opencode-go/glm-5.2",
        "intensity": "medium",
        "variant": None,
        "capability_tier": tier,
        "capability_profile": capability_profile("opencode-go/glm-5.2", tier, "medium"),
    }


def normalize_variant(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "default"}:
        return None
    if text in {"high", "max", "minimal"}:
        return text
    return None


def route_step(worker: str, model: str, variant: str | None, intensity: str, reason: str) -> dict[str, Any]:
    tier = normalize_capability_tier(variant if worker == "opencode" else None, intensity)
    return {
        "worker": worker,
        "model": model,
        "variant": variant,
        "intensity": intensity,
        "capability_tier": tier,
        "capability_profile": capability_profile(model, tier, intensity),
        "reason": reason,
    }


def single_file_target(task: dict[str, Any]) -> bool:
    target_paths = task.get("target_paths") or []
    return isinstance(target_paths, list) and len(target_paths) == 1
