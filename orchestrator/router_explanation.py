from __future__ import annotations

from typing import Any


def blocked_route_reason(route: dict[str, Any], task_shape: str) -> str:
    return f"{route.get('reason', 'BLOCKED')}; task_shape={task_shape}; budget_estimate_usd=0.00"


def route_reason(
    route: dict[str, Any],
    task_shape: str,
    history: dict[str, Any],
    budget_cap: float | None,
    estimate: float,
) -> str:
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
