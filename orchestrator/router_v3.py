from __future__ import annotations

from typing import Any

from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier
from .router_history import (
    choose_claude_model,
    estimate_route_cost,
    float_or_none,
    normalize_history,
)
from .router_task_shape import classify_task_shape


def apply_router_v3(
    route: dict[str, Any],
    task: dict[str, Any],
    project: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | dict[str, Any] | None = None,
    features: Any | None = None,
    labels: Any | None = None,
) -> dict[str, Any]:
    project = project or {}
    task_shape = classify_task_shape(task, features, labels)
    history_basis = normalize_history(history)
    budget_cap = float_or_none(task.get("budget_cap_usd") or project.get("budget_cap_usd"))
    route = dict(route)
    if route.get("blocked"):
        route["task_shape"] = task_shape
        route["budget_estimate_usd"] = 0.0
        route["budget_cap_usd"] = budget_cap
        route["history_basis"] = history_basis
        task_labels = dict(route.get("task_labels") or {})
        task_labels["task_shape"] = task_shape
        route["task_labels"] = task_labels
        route["retry_chain"] = []
        route["fallback_models"] = []
        route["reason"] = f"{route.get('reason', 'BLOCKED')}; task_shape={task_shape}; budget_estimate_usd=0.00"
        return route

    selected = _select_for_shape(task_shape, route, task, project, history_basis, budget_cap)
    if selected:
        route.update(selected)

    retry_chain = _retry_chain_for_shape(task_shape, route)
    route["retry_chain"] = retry_chain
    route["fallback_models"] = _fallback_models(retry_chain)
    route["max_retries"] = max(0, len(retry_chain) - 1)
    route["escalation_policy"] = "opencode_on_failure" if any(s["worker"] == "opencode" for s in retry_chain[1:]) else route.get("escalation_policy", "codex_review_or_needs_user")

    estimate = estimate_route_cost(retry_chain)
    route["task_shape"] = task_shape
    route["budget_estimate_usd"] = estimate
    route["budget_cap_usd"] = budget_cap
    route["history_basis"] = history_basis
    route["reason"] = _reason(route, task_shape, history_basis, budget_cap, estimate)
    route["agent_llm"] = agent_llm_name(str(route.get("selected_worker", "")), str(route.get("selected_model", "")))
    task_labels = dict(route.get("task_labels") or {})
    task_labels["task_shape"] = task_shape
    route["task_labels"] = task_labels
    route["capability_tier"] = normalize_capability_tier(route.get("capability_tier"), route.get("intensity"))
    route["capability_profile"] = route.get("capability_profile") or capability_profile(
        route.get("selected_model", ""),
        route.get("capability_tier"),
        route.get("intensity"),
    )
    return route


def _select_for_shape(
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
        return _opencode("max")
    if route.get("selected_worker") == "opencode" or project.get("default_worker") == "opencode":
        if project.get("default_worker") == "opencode" and task_type not in {"complex_coding"} and "glm" not in goal:
            variant = _normalize_variant(project.get("default_variant"))
        else:
            variant = _normalize_variant(route.get("variant"))
            if not variant and route.get("selected_model") == "opencode-go/glm-5.2":
                variant = _normalize_variant(project.get("default_variant"))
        return _opencode(variant) if variant else _opencode_without_variant()
    if "glm" in explicit_model or "glm" in goal:
        return _opencode("high")

    if task_shape == "docs_update":
        model = choose_claude_model(
            history,
            ["deepseek_flash", "deepseek_pro"],
            default="deepseek_flash" if route.get("selected_model") == "deepseek_flash" else "deepseek_pro",
            budget_cap=budget_cap,
            allow_low_cost=True,
        )
        return _claude(model, "low" if model == "deepseek_flash" else "medium")
    if task_shape == "open_bug_hunt":
        return _claude("deepseek_pro", "high")
    if task_shape == "targeted_patch":
        if _single_file_target(task):
            target_model = choose_claude_model(
                history,
                ["deepseek_flash", "deepseek_pro"],
                default="deepseek_pro",
                budget_cap=budget_cap,
                allow_low_cost=True,
            )
        else:
            target_model = "deepseek_pro"
        return _claude(target_model, "medium" if target_model == "deepseek_pro" else "low")
    if task_shape == "test_generation":
        return _claude("deepseek_pro", "medium")
    if task_shape == "large_refactor":
        return _opencode("max")
    if task_shape == "multimodal_analysis":
        return _claude("mimo_v25", "medium")
    if task_shape == "multimodal_to_code":
        return _claude("mimo_v25_pro", "high")
    if task_shape == "config_repair":
        return _claude("deepseek_pro", "medium")
    if task_shape == "review_only":
        return _claude("deepseek_pro", "medium")
    return None


def _retry_chain_for_shape(task_shape: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    primary = _step(
        str(route.get("selected_worker") or "claude_code"),
        str(route.get("selected_model") or "deepseek_pro"),
        route.get("variant"),
        str(route.get("intensity") or "medium"),
        "primary task_shape route",
    )
    if task_shape == "docs_update":
        fallback = "deepseek_pro" if primary["model"] == "deepseek_flash" else "deepseek_flash"
        return [primary, _step("claude_code", fallback, None, "medium", "docs_update fallback")]
    if task_shape == "targeted_patch":
        chain = [primary]
        if primary["model"] != "deepseek_pro":
            chain.append(_step("claude_code", "deepseek_pro", None, "medium", "targeted_patch stronger fallback"))
        chain.append(_step("opencode", "opencode-go/glm-5.2", "high", "high", "targeted_patch opencode fallback"))
        return chain
    if task_shape in {"open_bug_hunt", "test_generation", "config_repair", "multimodal_to_code"}:
        return [primary, _step("opencode", "opencode-go/glm-5.2", "high", "high", f"{task_shape} fallback")]
    if task_shape == "large_refactor":
        if primary["worker"] == "opencode" and primary.get("variant") == "max":
            return [
                primary,
                _step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor high fallback"),
            ]
        return [primary, _step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor fallback")]
    if task_shape == "multimodal_analysis":
        return [primary, _step("claude_code", "mimo_v25_pro", None, "high", "multimodal_analysis pro fallback")]
    return [primary]


def _reason(route: dict[str, Any], task_shape: str, history: dict[str, Any], budget_cap: float | None, estimate: float) -> str:
    selected_model = str(route.get("selected_model", ""))
    parts = [
        f"task_shape={task_shape}",
        f"selected={route.get('selected_worker')}/{selected_model}",
        f"budget_estimate_usd={estimate:.2f}",
    ]
    if budget_cap is not None:
        parts.append(f"budget_cap_usd={budget_cap:.2f}")
    if selected_model in history:
        item = history[selected_model]
        parts.append(
            f"history[{selected_model}].success_rate={item.get('success_rate')}; avg_cost={item.get('avg_cost')}"
        )
    elif history:
        parts.append("history=no_selected_model_record")
    else:
        parts.append("history=no_prior_metrics")
    decision = history.get("_decision") if isinstance(history.get("_decision"), dict) else None
    if decision:
        parts.append(
            "history_decision="
            f"{decision.get('selected')}; "
            f"scores={decision.get('scores')}"
        )
    if task_shape == "open_bug_hunt" and selected_model == "deepseek_pro":
        parts.append("open bug hunt avoids flash as primary")
    fallback = [s["model"] for s in route.get("retry_chain", [])[1:]]
    if fallback:
        parts.append(f"fallback={fallback}")
    return "; ".join(parts)


def _fallback_models(chain: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for step in chain[1:]:
        model = str(step.get("model", ""))
        if model and model not in seen:
            seen.append(model)
    return seen


def _claude(model: str, intensity: str) -> dict[str, Any]:
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


def _opencode(variant: str) -> dict[str, Any]:
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


def _opencode_without_variant() -> dict[str, Any]:
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


def _normalize_variant(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "default"}:
        return None
    if text in {"high", "max", "minimal"}:
        return text
    return None


def _step(worker: str, model: str, variant: str | None, intensity: str, reason: str) -> dict[str, Any]:
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


def _single_file_target(task: dict[str, Any]) -> bool:
    target_paths = task.get("target_paths") or []
    return isinstance(target_paths, list) and len(target_paths) == 1
