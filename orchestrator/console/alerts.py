from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from orchestrator.db import TaskDB


RUNNING_STATES = {"EXECUTING", "RUNNING", "VERIFYING", "CODEX_REVIEWING", "REVIEWING"}


def evaluate_alerts(db: TaskDB, stale_seconds: int = 120) -> list[dict[str, Any]]:
    now_ts = time.time()
    opened: list[dict[str, Any]] = []
    for heartbeat in db.list_worker_heartbeats(limit=500):
        if heartbeat.get("status") not in RUNNING_STATES and heartbeat.get("phase") not in RUNNING_STATES:
            continue
        ts = _parse_ts(heartbeat.get("ts"))
        if ts is None or now_ts - ts <= stale_seconds:
            continue
        alert = {
            "alert_id": f"worker_no_heartbeat:{heartbeat.get('worker_id')}:{heartbeat.get('attempt_id')}",
            "ts": _now(),
            "severity": "high",
            "source": "console.alerts",
            "task_id": heartbeat.get("task_id"),
            "rule_id": "worker_no_heartbeat",
            "title": "Worker heartbeat is stale",
            "message": f"Worker {heartbeat.get('worker_id')} has no heartbeat for more than {stale_seconds}s.",
            "status": "open",
            "resolved_at": None,
        }
        db.upsert_system_alert(alert)
        opened.append(alert)
    return opened


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

