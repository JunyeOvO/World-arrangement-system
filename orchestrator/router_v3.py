from __future__ import annotations

from typing import Any

from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier
from .router_history import (
    estimate_route_cost,
    float_or_none,
    normalize_history,
)
from .router_route_policy import fallback_models, retry_chain_for_shape, select_for_shape
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

    selected = select_for_shape(task_shape, route, task, project, history_basis, budget_cap)
    if selected:
        route.update(selected)

    retry_chain = retry_chain_for_shape(task_shape, route)
    route["retry_chain"] = retry_chain
    route["fallback_models"] = fallback_models(retry_chain)
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
