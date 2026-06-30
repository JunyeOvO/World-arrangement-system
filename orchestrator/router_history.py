from __future__ import annotations

from typing import Any


MODEL_COST_ESTIMATES = {
    "deepseek_flash": 0.08,
    "deepseek_pro": 0.30,
    "mimo_v25": 0.20,
    "mimo_v25_pro": 0.40,
    "opencode-go/glm-5.2": 0.55,
    "opencode_go_glm52": 0.55,
}

MIN_HISTORY_ATTEMPTS = 3


def normalize_history(history: list[dict[str, Any]] | dict[str, Any] | None) -> dict[str, Any]:
    if not history:
        return {}
    if isinstance(history, dict):
        result: dict[str, Any] = {}
        for model, row in history.items():
            if not isinstance(row, dict):
                continue
            result[str(model)] = history_item(row, str(model))
        return result
    result: dict[str, Any] = {}
    for row in history:
        model = str(row.get("model") or "")
        if not model:
            continue
        result[model] = history_item(row, model)
    return result


def choose_claude_model(
    history: dict[str, Any],
    models: list[str],
    default: str,
    budget_cap: float | None,
    allow_low_cost: bool,
) -> str:
    eligible = [model for model in models if within_budget(model, budget_cap)]
    if not eligible:
        eligible = models[:]
    reliable = {
        model
        for model in eligible
        if has_reliable_history(history.get(model))
    }
    if default in eligible and not reliable:
        return default
    if default not in eligible and not reliable:
        return min(eligible, key=lambda model: MODEL_COST_ESTIMATES.get(model, 0.30))
    scored: dict[str, float] = {}
    for model in eligible:
        scored[model] = history_model_score(history.get(model), model, allow_low_cost)
    selected = max(eligible, key=lambda model: (scored[model], -MODEL_COST_ESTIMATES.get(model, 0.30)))
    if scored[selected] <= 0 and default in eligible:
        selected = default
    elif default in eligible and abs(scored[selected] - scored[default]) < 0.04:
        selected = default
    history["_decision"] = {
        "selected": selected,
        "default": default,
        "scores": {model: round(scored.get(model, 0.0), 3) for model in eligible},
    }
    return selected


def estimate_route_cost(chain: list[dict[str, Any]]) -> float:
    total = 0.0
    for idx, step in enumerate(chain):
        multiplier = 1.0 if idx == 0 else 0.35
        total += MODEL_COST_ESTIMATES.get(str(step.get("model")), 0.30) * multiplier
    return round(total, 4)


def within_budget(model: str, budget_cap: float | None) -> bool:
    return budget_cap is None or MODEL_COST_ESTIMATES.get(model, 0.30) <= budget_cap


def has_reliable_history(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    success_rate = float_or_none(item.get("success_rate"))
    if success_rate is None:
        return False
    attempts = int_or_none(item.get("attempts"))
    return attempts is None or attempts >= MIN_HISTORY_ATTEMPTS


def history_model_score(item: dict[str, Any] | None, model: str, allow_low_cost: bool) -> float:
    base_cost = MODEL_COST_ESTIMATES.get(model, 0.30)
    cost_score = (1.0 / max(base_cost, 0.01)) * 0.01 if allow_low_cost else 0.0
    if not item:
        return 0.5 + cost_score
    success_rate = float_or_none(item.get("success_rate"))
    if success_rate is None:
        success_rate = 0.5
    attempts = int_or_none(item.get("attempts"))
    if attempts is None:
        evidence = 0.55
    elif attempts <= 0:
        evidence = 0.0
    elif attempts < MIN_HISTORY_ATTEMPTS:
        evidence = 0.2
    else:
        evidence = min(1.0, attempts / 12.0)
    avg_cost = float_or_none(item.get("avg_cost"))
    observed_cost_score = 0.0
    if allow_low_cost and avg_cost is not None and avg_cost > 0:
        observed_cost_score = min(0.18, 0.02 / avg_cost)
    return (success_rate * evidence) + ((1.0 - evidence) * 0.5) + cost_score + observed_cost_score


def history_item(row: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "success_rate": float_or_none(row.get("success_rate")),
        "avg_cost": float_or_none(row.get("avg_cost_usd") if "avg_cost_usd" in row else row.get("avg_cost")),
        "attempts": int_or_none(row.get("attempts")),
        "worker": row.get("worker"),
        "model": model,
    }


def float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
