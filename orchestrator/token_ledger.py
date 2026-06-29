from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .db import TaskDB
from .pricing import calculate_token_cost_usd, has_price


LEDGER_VERSION = 1


def build_task_token_ledger(db: TaskDB, task_id: str) -> dict[str, Any]:
    task = db.get_task(task_id) or {"task_id": task_id}
    metrics = db.list_task_metrics(task_id)
    codex_events = list(reversed(db.list_codex_usage_events(task_id=task_id, limit=2000)))

    codex = _codex_section(codex_events)
    worker = _worker_section(metrics)
    combined_total = codex["total_tokens"] + worker["total_tokens"]
    codex_share_pct = round((codex["total_tokens"] / combined_total) * 100, 2) if combined_total else 0.0

    return {
        "version": LEDGER_VERSION,
        "task_id": task_id,
        "project_id": task.get("project_id"),
        "task_status": task.get("status"),
        "generated_at": _now(),
        "codex": codex,
        "worker": worker,
        "combined": {
            "input_tokens": codex["input_tokens"] + worker["input_tokens"],
            "output_tokens": codex["output_tokens"] + worker["output_tokens"],
            "cache_read_input_tokens": worker["cache_read_input_tokens"],
            "total_tokens": combined_total,
            "known_cost_usd": worker["calculated_cost_usd"],
            "cost_source": "worker_model_token_pricing_only",
            "cost_note": (
                "Codex quota/cost telemetry is not exposed locally; Codex planning/review "
                "tokens are estimated and excluded from USD cost."
            ),
        },
        "quota_evidence": {
            "codex_share_pct": codex_share_pct,
            "worker_share_pct": round(100 - codex_share_pct, 2) if combined_total else 0.0,
            "codex_event_count": codex["event_count"],
            "actual_codex_event_count": codex["actual_event_count"],
            "codex_token_source": "estimated_utf8_payloads",
            "worker_token_source": "adapter_reported_stream_metrics",
            "memory_hit_count": worker["memory_hit_count"],
            "memory_miss_count": worker["memory_miss_count"],
            "cache_read_input_tokens": worker["cache_read_input_tokens"],
        },
        "counterfactual": {
            "status": "not_measured",
            "reason": (
                "A same-task no-World Codex baseline is required before claiming measured "
                "Codex quota savings."
            ),
        },
    }


def write_task_token_ledger(db: TaskDB, task_id: str, output: Path) -> Path:
    ledger = build_task_token_ledger(db, task_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _codex_section(events: list[dict[str, Any]]) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    actual_total_tokens = 0
    estimated_total_tokens = 0
    methods: set[str] = set()
    for event in events:
        event_input = _int(event.get("input_tokens"))
        event_output = _int(event.get("output_tokens"))
        event_total = _int(event.get("total_tokens")) or event_input + event_output
        actual = bool(event.get("actual_codex_used"))
        method = str(event.get("estimation_method") or "")
        if method:
            methods.add(method)
        input_tokens += event_input
        output_tokens += event_output
        total_tokens += event_total
        if actual:
            actual_total_tokens += event_total
        else:
            estimated_total_tokens += event_total
        phases.append({
            "phase": event.get("phase"),
            "input_tokens": event_input,
            "output_tokens": event_output,
            "total_tokens": event_total,
            "actual_codex_used": actual,
            "estimation_method": method,
            "created_at": event.get("created_at"),
        })
    return {
        "event_count": len(events),
        "actual_event_count": sum(1 for event in events if bool(event.get("actual_codex_used"))),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "actual_total_tokens": actual_total_tokens,
        "estimated_total_tokens": estimated_total_tokens,
        "estimation_methods": sorted(methods),
        "cost_usd": None,
        "cost_source": "not_available",
        "phases": phases,
    }


def _worker_section(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = sum(_int(row.get("input_tokens")) for row in metrics)
    output_tokens = sum(_int(row.get("output_tokens")) for row in metrics)
    cache_tokens = sum(_int(row.get("cache_read_input_tokens")) for row in metrics)
    calculated_cost = sum(calculate_token_cost_usd(row) for row in metrics)
    adapter_cost = sum(_float(row.get("total_cost_usd")) for row in metrics if row.get("total_cost_usd") is not None)
    priced_attempts = sum(1 for row in metrics if has_price(row.get("model")))
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for row in metrics:
        key = (str(row.get("worker") or ""), str(row.get("model") or ""))
        model = models.setdefault(key, {
            "worker": key[0],
            "model": key[1],
            "attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "calculated_cost_usd": 0.0,
        })
        model["attempts"] += 1
        model["input_tokens"] += _int(row.get("input_tokens"))
        model["output_tokens"] += _int(row.get("output_tokens"))
        model["cache_read_input_tokens"] += _int(row.get("cache_read_input_tokens"))
        model["calculated_cost_usd"] += calculate_token_cost_usd(row)
    model_rows = []
    for item in models.values():
        item["total_tokens"] = (
            item["input_tokens"] + item["output_tokens"] + item["cache_read_input_tokens"]
        )
        item["calculated_cost_usd"] = round(float(item["calculated_cost_usd"]), 6)
        model_rows.append(item)
    model_rows.sort(key=lambda row: (-int(row["attempts"]), str(row["model"])))
    return {
        "attempts": len(metrics),
        "priced_attempts": priced_attempts,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_tokens,
        "total_tokens": input_tokens + output_tokens + cache_tokens,
        "calculated_cost_usd": round(float(calculated_cost), 6),
        "adapter_reported_cost_usd": round(float(adapter_cost), 6),
        "memory_hit_count": sum(_int(row.get("memory_hit_count")) for row in metrics),
        "memory_miss_count": sum(_int(row.get("memory_miss_count")) for row in metrics),
        "models": model_rows,
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
