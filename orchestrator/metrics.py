from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TaskMetrics:
    task_id: str
    attempt_no: int
    worker: str
    model: str
    status: str
    failure_reason: str | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    changed_files_count: int = 0
    build_passed: bool | None = None
    review_approved: bool | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = row["created_at"] or _now()
        return row


def collect_task_metrics(
    *,
    task_id: str,
    attempt_no: int,
    worker: str,
    model: str,
    status: str,
    stream_path: str | None = None,
    changed_files_count: int = 0,
    failure_reason: str | None = None,
    build_passed: bool | None = None,
    review_approved: bool | None = None,
) -> TaskMetrics:
    stream = parse_worker_stream(Path(stream_path)) if stream_path else {}
    return TaskMetrics(
        task_id=task_id,
        attempt_no=attempt_no,
        worker=worker,
        model=model,
        status=status,
        failure_reason=failure_reason or stream.get("failure_reason"),
        total_cost_usd=_float_or_none(stream.get("total_cost_usd")),
        duration_ms=_int_or_none(stream.get("duration_ms")),
        duration_api_ms=_int_or_none(stream.get("duration_api_ms")),
        num_turns=_int_or_none(stream.get("num_turns")),
        input_tokens=_int_or_none(stream.get("input_tokens")),
        output_tokens=_int_or_none(stream.get("output_tokens")),
        cache_read_input_tokens=_int_or_none(stream.get("cache_read_input_tokens")),
        changed_files_count=changed_files_count,
        build_passed=build_passed,
        review_approved=review_approved,
        created_at=_now(),
    )


def parse_worker_stream(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    metrics: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        _merge_event_metrics(metrics, event)
    return metrics


def write_metrics(metrics: TaskMetrics, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _merge_event_metrics(metrics: dict[str, Any], event: dict[str, Any]) -> None:
    result = event.get("result") if isinstance(event.get("result"), dict) else event
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}

    for key in ("total_cost_usd", "duration_ms", "duration_api_ms", "num_turns"):
        if key in result:
            metrics[key] = result[key]

    for source_key, target_key in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cache_read_input_tokens", "cache_read_input_tokens"),
    ):
        if source_key in usage:
            metrics[target_key] = usage[source_key]
        elif source_key in result:
            metrics[target_key] = result[source_key]

    subtype = result.get("subtype") or result.get("error")
    if isinstance(subtype, str) and subtype:
        metrics["failure_reason"] = subtype


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
