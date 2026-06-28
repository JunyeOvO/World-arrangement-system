from __future__ import annotations

import json
import time
from collections.abc import Iterator

from orchestrator.db import TaskDB

from .alerts import evaluate_alerts
from .serializers import event_view


EVENT_TYPE_MAP = {
    "created": "task.created",
    "routed": "task.updated",
    "worker_started": "attempt.started",
    "worker_failed": "attempt.failed",
    "verify_completed": "verify.completed",
    "review_completed": "review.completed",
    "awaiting_hard_approval": "approval.required",
    "awaiting_soft_approval": "approval.required",
    "approval_decided": "approval.resolved",
}


def sse_stream(
    db: TaskDB,
    after_id: int | None = None,
    poll_seconds: float = 0.25,
    max_events: int | None = None,
) -> Iterator[bytes]:
    last_id = after_id
    sent = 0
    emitted_alert_ids: set[str] = set()
    while max_events is None or sent < max_events:
        rows = db.list_recent_events(limit=100, after_id=last_id)
        alerts = evaluate_alerts(db)
        if not rows and not alerts:
            if max_events is not None:
                break
            yield b": keepalive\n\n"
            time.sleep(poll_seconds)
            continue
        for row in rows:
            last_id = int(row["id"])
            payload = event_view(row)
            event_type = EVENT_TYPE_MAP.get(str(row.get("event_type")), "task.updated")
            yield _format_sse(event_type, payload, last_id)
            sent += 1
            if max_events is not None and sent >= max_events:
                return
        for alert in alerts:
            alert_id = str(alert.get("alert_id"))
            if alert_id in emitted_alert_ids:
                continue
            emitted_alert_ids.add(alert_id)
            yield _format_sse("alert.opened", alert, None)
            sent += 1
            if max_events is not None and sent >= max_events:
                return


def _format_sse(event_type: str, payload: dict, event_id: int | None) -> bytes:
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event_type}")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    parts.append(f"data: {data}")
    return ("\n".join(parts) + "\n\n").encode("utf-8")

