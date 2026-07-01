from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .control_files import write_json_file
from .db import TaskDB
from .pricing import calculate_token_cost_usd, has_price


LEDGER_VERSION = 1


def build_task_token_ledger(db: TaskDB, task_id: str) -> dict[str, Any]:
    snapshot = _task_ledger_snapshot(db, task_id)
    task = snapshot["task"] or {"task_id": task_id}
    metrics = snapshot["metrics"]
    codex_events = snapshot["codex_events"]
    baselines = snapshot["baselines"]

    codex = _codex_section(codex_events)
    worker = _worker_section(metrics)
    counterfactual = _counterfactual_section(codex, baselines)
    combined_total = codex["total_tokens"] + worker["total_tokens"]
    codex_share_pct = round((codex["total_tokens"] / combined_total) * 100, 2) if combined_total else 0.0

    return {
        "version": LEDGER_VERSION,
        "task_id": task_id,
        "project_id": task.get("project_id"),
        "task_status": task.get("status"),
        "generated_at": _now(),
        "read_consistency": "single_sqlite_transaction",
        "codex": codex,
        "worker": worker,
        "combined": {
            "input_tokens": codex["input_tokens"] + worker["input_tokens"],
            "output_tokens": codex["output_tokens"] + worker["output_tokens"],
            "cache_read_input_tokens": worker["cache_read_input_tokens"],
            "total_tokens": combined_total,
            "known_cost_usd": worker["calculated_cost_usd"],
            "worker_pricing_complete": worker["pricing_complete"],
            "unpriced_worker_attempts": worker["unpriced_attempts"],
            "cost_source": "worker_model_token_pricing_only",
            "cost_note": _combined_cost_note(worker),
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
        "baselines": baselines,
        "counterfactual": counterfactual,
    }


def write_task_token_ledger(db: TaskDB, task_id: str, output: Path) -> Path:
    ledger = build_task_token_ledger(db, task_id)
    write_json_file(output, ledger)
    return output


def _task_ledger_snapshot(db: TaskDB, task_id: str) -> dict[str, Any]:
    db.init()
    with db.connect() as con:
        con.execute("BEGIN")
        task_row = con.execute("SELECT * FROM tasks WHERE task_id=?", [task_id]).fetchone()
        metrics_rows = con.execute(
            "SELECT * FROM task_metrics WHERE task_id=? ORDER BY attempt_no ASC",
            [task_id],
        ).fetchall()
        codex_rows = con.execute(
            """
            SELECT * FROM codex_usage_events
            WHERE task_id=?
            ORDER BY created_at ASC, id ASC
            LIMIT 2000
            """,
            [task_id],
        ).fetchall()
        baseline_rows = con.execute(
            """
            SELECT * FROM task_baselines
            WHERE task_id=?
            ORDER BY actual_codex_used DESC, created_at DESC, id DESC
            LIMIT 50
            """,
            [task_id],
        ).fetchall()
    return {
        "task": dict(task_row) if task_row else None,
        "metrics": [dict(row) for row in metrics_rows],
        "codex_events": [_decode_codex_event(dict(row)) for row in codex_rows],
        "baselines": [_decode_baseline(dict(row)) for row in baseline_rows],
    }


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
    unpriced_attempts = len(metrics) - priced_attempts
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for row in metrics:
        key = (str(row.get("worker") or ""), str(row.get("model") or ""))
        model = models.setdefault(key, {
            "worker": key[0],
            "model": key[1],
            "attempts": 0,
            "priced_attempts": 0,
            "unpriced_attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "calculated_cost_usd": 0.0,
        })
        model["attempts"] += 1
        if has_price(row.get("model")):
            model["priced_attempts"] += 1
        else:
            model["unpriced_attempts"] += 1
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
        item["pricing_complete"] = int(item["unpriced_attempts"]) == 0
        model_rows.append(item)
    model_rows.sort(key=lambda row: (-int(row["attempts"]), str(row["model"])))
    return {
        "attempts": len(metrics),
        "priced_attempts": priced_attempts,
        "unpriced_attempts": unpriced_attempts,
        "pricing_complete": unpriced_attempts == 0,
        "cost_note": (
            "All worker attempts use configured model prices."
            if unpriced_attempts == 0
            else f"{unpriced_attempts} worker attempt(s) have no configured model price; calculated_cost_usd excludes them."
        ),
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


def _combined_cost_note(worker: dict[str, Any]) -> str:
    note = (
        "Codex quota/cost telemetry is not exposed locally; Codex planning/review "
        "tokens are estimated and excluded from USD cost."
    )
    unpriced_attempts = _int(worker.get("unpriced_attempts"))
    if unpriced_attempts:
        note += (
            f" Worker known_cost_usd also excludes {unpriced_attempts} attempt(s) "
            "with no configured model price."
        )
    return note


def _counterfactual_section(codex: dict[str, Any], baselines: list[dict[str, Any]]) -> dict[str, Any]:
    if not baselines:
        return {
            "status": "not_measured",
            "reason": (
                "A same-task no-World Codex baseline is required before claiming measured "
                "Codex quota savings."
            ),
        }
    baseline = baselines[0]
    baseline_total = _int(baseline.get("total_tokens"))
    world_codex_total = _int(codex.get("total_tokens"))
    saved_tokens = baseline_total - world_codex_total
    reduction_pct = round((saved_tokens / baseline_total) * 100, 2) if baseline_total > 0 else 0.0
    actual = bool(baseline.get("actual_codex_used"))
    return {
        "status": "measured" if actual else "estimated",
        "baseline_kind": baseline.get("baseline_kind"),
        "baseline_source": baseline.get("source"),
        "baseline_estimation_method": baseline.get("estimation_method"),
        "baseline_total_tokens": baseline_total,
        "world_codex_total_tokens": world_codex_total,
        "codex_tokens_saved": saved_tokens,
        "codex_reduction_pct": reduction_pct,
        "claim_strength": "actual_codex_only_baseline" if actual else "replay_estimate_only",
        "reason": (
            "Actual same-task Codex-only tokens were recorded."
            if actual
            else "Replay estimate is useful for trend analysis but is not measured Codex quota usage."
        ),
    }


def _decode_codex_event(row: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = row.pop("metadata_json", None)
    row["metadata"] = _decode_json_object(raw_metadata)
    row["actual_codex_used"] = bool(row.get("actual_codex_used"))
    return row


def _decode_baseline(row: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = row.pop("metadata_json", None)
    row["metadata"] = _decode_json_object(raw_metadata)
    row["actual_codex_used"] = bool(row.get("actual_codex_used"))
    return row


def _decode_json_object(value: Any) -> dict[str, Any]:
    import json

    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


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
