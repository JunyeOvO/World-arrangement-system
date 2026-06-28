from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB

from .alerts import evaluate_alerts
from .serializers import (
    alert_view,
    artifact_allowed,
    artifact_listing,
    event_view,
    heartbeat_view,
    metric_view,
    task_summary,
)


TERMINAL_SUCCESS = {"DONE", "COMPLETED", "COMPLETED_WITH_PATCH", "PR_CREATED"}
TERMINAL_FAILED = {"FAILED", "FAILED_FINAL"}
RUNNING = {"EXECUTING", "RUNNING", "VERIFYING", "CODEX_REVIEWING", "REVIEWING"}
APPROVAL_WAITING = {"HARD_APPROVAL_WAITING", "SOFT_APPROVAL_WAITING", "NEEDS_USER", "BLOCKED"}
HEARTBEAT_FRESH_SECONDS = 120


class ConsoleQueries:
    def __init__(self, db: TaskDB, artifacts: ArtifactStore):
        self.db = db
        self.artifacts = artifacts

    def snapshot(self) -> dict[str, Any]:
        evaluate_alerts(self.db)
        alerts = [alert_view(row) for row in self.db.list_system_alerts(status="open", limit=50)]
        heartbeats = [heartbeat_view(row) for row in self.db.list_worker_heartbeats(limit=50)]
        live_task_ids = _live_task_ids(heartbeats)
        dismissed = self.db.list_console_dismissed_task_ids()
        tasks = [
            _with_runtime_liveness(task_summary(row), live_task_ids)
            for row in self.db.list_tasks(limit=100)
            if row.get("task_id") not in dismissed
        ]
        metrics = self.metrics_summary()
        counts = _status_counts(tasks)
        return {
            "health": {
                "status": "alerting" if alerts else "healthy",
                "running": counts["running"],
                "queued": counts["queued"],
                "failed": counts["failed"],
                "approval_waiting": counts["approval_waiting"],
                "open_alerts": len(alerts),
                "cost_today_usd": metrics["total_cost_usd"],
            },
            "tasks": tasks,
            "alerts": alerts,
            "heartbeats": heartbeats,
            "metrics": metrics,
            "models": self.model_metrics(),
        }

    def list_tasks(
        self,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        dismissed = self.db.list_console_dismissed_task_ids()
        return {
            "tasks": [
                task_summary(row)
                for row in self.db.list_tasks(status, project_id, limit)
                if row.get("task_id") not in dismissed
            ]
        }

    def task_detail(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        events = [event_view(row) for row in self.db.list_events(task_id)]
        metrics = [metric_view(row) for row in self.db.list_task_metrics(task_id)]
        artifact_index = self.artifacts.index(task_id)
        route = self._read_artifact_json(artifact_index, "route.json")
        approval = self._read_artifact_json(artifact_index, "approval.json")
        verify = self._read_artifact_json(artifact_index, "verify/verify.json")
        review = self._read_artifact_json(artifact_index, "review/review.json")
        return {
            "task": task_summary(task),
            "timeline": events,
            "route_decision": route,
            "approval": approval,
            "verify": verify,
            "review": review,
            "metrics": metrics,
            "artifacts": artifact_listing(task_id, artifact_index),
        }

    def task_timeline(self, task_id: str) -> dict[str, Any]:
        return {"task_id": task_id, "timeline": [event_view(row) for row in self.db.list_events(task_id)]}

    def task_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        return {"task_id": task_id, "artifacts": artifact_listing(task_id, self.artifacts.index(task_id))}

    def read_artifact_text(self, task_id: str, relative: str) -> tuple[int, str, str]:
        if not artifact_allowed(relative):
            return 403, "text/plain; charset=utf-8", "artifact path is not whitelisted"
        task = self.db.get_task(task_id)
        if not task:
            return 404, "text/plain; charset=utf-8", "task not found"
        index = self.artifacts.index(task_id)
        path = index.get(relative)
        if not path:
            return 404, "text/plain; charset=utf-8", "artifact not found"
        base = Path(task["run_dir"]).resolve()
        target = Path(path).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return 403, "text/plain; charset=utf-8", "artifact escaped run directory"
        return 200, _content_type(relative), target.read_text(encoding="utf-8", errors="replace")[:100_000]

    def metrics_summary(self) -> dict[str, Any]:
        tasks = self.db.list_tasks(limit=500)
        rows: list[dict[str, Any]] = []
        for task in tasks:
            rows.extend(self.db.list_task_metrics(task["task_id"]))
        total = sum(float(row.get("total_cost_usd") or 0) for row in rows)
        durations = sorted(int(row.get("duration_ms") or 0) for row in rows)
        p95 = durations[int(len(durations) * 0.95) - 1] if durations else 0
        failures: dict[str, int] = {}
        for row in rows:
            reason = row.get("failure_reason") or "none"
            failures[str(reason)] = failures.get(str(reason), 0) + 1
        return {
            "attempts": len(rows),
            "total_cost_usd": round(total, 6),
            "p95_duration_ms": p95,
            "failure_reasons": failures,
        }

    def model_metrics(self) -> list[dict[str, Any]]:
        return [metric_view(row) for row in self.db.model_metrics_summary()]

    def audit(self, task_id: str | None = None, action: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"events": [event_view(row) for row in self.db.list_audit_events(task_id, action, limit)]}

    def alerts(self, status: str | None = "open") -> dict[str, Any]:
        evaluate_alerts(self.db)
        return {"alerts": [alert_view(row) for row in self.db.list_system_alerts(status=status, limit=100)]}

    def config_effective(self, project_id: str | None = None) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "redaction": "enabled",
            "artifact_whitelist": sorted(list(__import__("orchestrator.console.serializers", fromlist=["PUBLIC_ARTIFACTS"]).PUBLIC_ARTIFACTS)),
            "actions": ["cancel", "retry", "approve", "reject", "resolve_alert"],
        }

    def _read_artifact_json(self, artifact_index: dict[str, str], relative: str) -> dict[str, Any] | None:
        path = artifact_index.get(relative)
        if not path:
            return None
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else {"value": value}


def _status_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"running": 0, "queued": 0, "failed": 0, "approval_waiting": 0}
    for task in tasks:
        status = str(task.get("status") or "")
        runtime = task.get("runtime") if isinstance(task.get("runtime"), dict) else {}
        if status in RUNNING and runtime.get("live") is True:
            counts["running"] += 1
        if status in {"QUEUED", "NEW", "PLANNED", "ROUTED"}:
            counts["queued"] += 1
        if status in TERMINAL_FAILED:
            counts["failed"] += 1
        if status in APPROVAL_WAITING:
            counts["approval_waiting"] += 1
    return counts


def _with_runtime_liveness(task: dict[str, Any], live_task_ids: set[str]) -> dict[str, Any]:
    status = str(task.get("status") or "")
    task_id = str(task.get("task_id") or "")
    live = status in RUNNING and task_id in live_task_ids
    task["runtime"] = {
        "live": live,
        "stale": status in RUNNING and not live,
    }
    return task


def _live_task_ids(heartbeats: list[dict[str, Any]]) -> set[str]:
    now = time.time()
    live: set[str] = set()
    for heartbeat in heartbeats:
        task_id = heartbeat.get("task_id")
        if not task_id:
            continue
        status = str(heartbeat.get("status") or heartbeat.get("phase") or "")
        phase = str(heartbeat.get("phase") or "")
        if status not in RUNNING and phase not in RUNNING:
            continue
        ts = _parse_ts(heartbeat.get("ts"))
        if ts is not None and now - ts <= HEARTBEAT_FRESH_SECONDS:
            live.add(str(task_id))
    return live


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _content_type(relative: str) -> str:
    if relative.endswith(".json"):
        return "application/json; charset=utf-8"
    if relative.endswith(".patch"):
        return "text/x-diff; charset=utf-8"
    return "text/plain; charset=utf-8"
