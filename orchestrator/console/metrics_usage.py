from __future__ import annotations

from typing import Any

from .pricing import calculate_token_cost_usd


def build_metrics_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cost_by_day_model: dict[tuple[str, str], float] = {}
    dates: set[str] = set()
    models: set[str] = set()
    calls: list[dict[str, Any]] = []
    for row in rows:
        created_at = str(row.get("created_at") or "")
        date = metric_date(created_at)
        model = str(row.get("model") or "unknown")
        cost = calculate_token_cost_usd(row)
        dates.add(date)
        models.add(model)
        cost_by_day_model[(date, model)] = cost_by_day_model.get((date, model), 0.0) + cost
        calls.append({
            "created_at": created_at,
            "date": date,
            "model": model,
            "worker": row.get("worker") or "",
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "cache_read_input_tokens": int(row.get("cache_read_input_tokens") or 0),
            "cost_usd": round(cost, 6),
            "task_id": row.get("task_id") or "",
            "attempt_no": row.get("attempt_no"),
            "session": session_label(str(row.get("task_id") or "")),
        })
    return {
        "cost_series": {
            "dates": sorted(dates),
            "models": sorted(models),
            "rows": [
                {"date": date, "model": model, "cost_usd": round(cost, 6)}
                for (date, model), cost in sorted(cost_by_day_model.items())
            ],
        },
        "calls": calls,
    }


def metric_date(created_at: str) -> str:
    if not created_at:
        return "unknown"
    return created_at[:10]


def session_label(task_id: str) -> str:
    return task_id[-8:] if len(task_id) > 8 else task_id
