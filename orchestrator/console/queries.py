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


TERMINAL_SUCCESS = {
    "DONE",
    "COMPLETED",
    "COMPLETED_WITH_PATCH",
    "COMPLETED_NO_CHANGES",
    "DRY_RUN_COMPLETED",
    "PR_CREATED",
}
TERMINAL_FAILED = {"FAILED", "FAILED_FINAL"}
RUNNING = {"EXECUTING", "RUNNING", "VERIFYING", "CODEX_REVIEWING", "REVIEWING"}
QUEUED = {
    "QUEUED",
    "NEW",
    "CLASSIFIED",
    "DYNAMIC_RISK_SCORED",
    "APPROVAL_DECIDED",
    "AUTO_SILENT",
    "AUTO_WITH_SUMMARY",
    "PLANNED",
    "ROUTED",
    "WORKTREE_CREATED",
    "WORKTREE_READY",
    "RETRYING",
}
APPROVAL_WAITING = {"HARD_APPROVAL_WAITING", "SOFT_APPROVAL_WAITING", "NEEDS_USER", "BLOCKED"}
HEARTBEAT_FRESH_SECONDS = 120
PROCESS_TERMINAL_DISPLAY = {
    "succeeded": "WORKER_SUCCEEDED",
    "failed": "WORKER_FAILED",
    "timed_out": "WORKER_TIMED_OUT",
    "cancelled": "WORKER_CANCELLED",
}
PROCESS_FAILED_DISPLAY = {"WORKER_FAILED", "WORKER_TIMED_OUT"}
PROCESS_RUNNING = {"running"}
CONSOLE_GROUP_DESCRIPTIONS = {
    "running": "Fresh worker heartbeat/control heartbeat exists; this is actively executing now.",
    "queued": "Task is accepted and can continue without user input, but no worker is currently live.",
    "failed": "Task or worker reached a failure state that needs retry, dismissal, or investigation.",
    "approval": "Task is paused for user approval, user input, or policy decision; NEEDS_USER belongs here.",
    "alerts": "System-level alerts such as stale worker heartbeats; this is not a task lifecycle bucket.",
    "none": "Completed, cancelled, stale-without-failure, or otherwise not actionable from the top status strip.",
}


class ConsoleQueries:
    def __init__(self, db: TaskDB, artifacts: ArtifactStore):
        self.db = db
        self.artifacts = artifacts

    def snapshot(self) -> dict[str, Any]:
        evaluate_alerts(self.db)
        alerts = [alert_view(row) for row in self.db.list_system_alerts(status="open", limit=50)]
        heartbeats = [heartbeat_view(row) for row in self.db.list_worker_heartbeats(limit=50)]
        live_task_ids = _live_task_ids(heartbeats)
        raw_tasks = self.db.list_tasks(limit=100)
        _auto_dismiss_superseded_stale_running_tasks(self.db, raw_tasks, live_task_ids)
        dismissed = self.db.list_console_dismissed_task_ids()
        tasks = [
            _with_runtime_liveness(task_summary(row), live_task_ids, row)
            for row in raw_tasks
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
        heartbeats = [heartbeat_view(row) for row in self.db.list_worker_heartbeats(limit=50)]
        live_task_ids = _live_task_ids(heartbeats)
        events = [event_view(row) for row in self.db.list_events(task_id)]
        metrics = [metric_view(row) for row in self.db.list_task_metrics(task_id)]
        artifact_index = self.artifacts.index(task_id)
        route = self._read_artifact_json(artifact_index, "route.json")
        approval = self._read_artifact_json(artifact_index, "approval.json")
        verify = self._read_artifact_json(artifact_index, "verify/verify.json")
        review = self._read_artifact_json(artifact_index, "review/review.json")
        return {
            "task": _with_runtime_liveness(task_summary(task), live_task_ids, task),
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

    def metrics_usage(self, limit: int = 200) -> dict[str, Any]:
        rows = [metric_view(row) for row in self.db.list_recent_task_metrics(limit=limit)]
        cost_by_day_model: dict[tuple[str, str], float] = {}
        dates: set[str] = set()
        models: set[str] = set()
        calls: list[dict[str, Any]] = []
        for row in rows:
            created_at = str(row.get("created_at") or "")
            date = _metric_date(created_at)
            model = str(row.get("model") or "unknown")
            cost = float(row.get("total_cost_usd") or 0)
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
                "session": _session_label(str(row.get("task_id") or "")),
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
        group = str(task.get("console_group") or "")
        if group == "running":
            counts["running"] += 1
        if group == "queued":
            counts["queued"] += 1
        if group == "failed":
            counts["failed"] += 1
        if group == "approval":
            counts["approval_waiting"] += 1
    return counts


def _with_runtime_liveness(
    task: dict[str, Any],
    live_task_ids: set[str],
    raw_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(task.get("status") or "")
    task_id = str(task.get("task_id") or "")
    raw = raw_task or task
    process = _read_control_json(raw.get("run_dir"), "process.json")
    control_heartbeat = _read_control_json(raw.get("run_dir"), "heartbeat.json")
    control_live = _control_heartbeat_live(control_heartbeat)
    live = status in RUNNING and (task_id in live_task_ids or control_live)
    runtime: dict[str, Any] = {
        "live": live,
        "stale": status in RUNNING and not live,
    }
    process_status = str(process.get("status") or "")
    process_finished = bool(process_status in PROCESS_TERMINAL_DISPLAY or process.get("finished_at"))
    if process_status:
        runtime["process_status"] = process_status
        runtime["process_finished"] = process_finished
    control_heartbeat_status = str(control_heartbeat.get("status") or "")
    if control_heartbeat_status:
        runtime["control_heartbeat_status"] = control_heartbeat_status
        runtime["control_heartbeat_live"] = control_live
    task["runtime"] = runtime
    if status in RUNNING and not live and process_status in PROCESS_TERMINAL_DISPLAY:
        task["display_status"] = PROCESS_TERMINAL_DISPLAY[process_status]
        task["status_note"] = (
            f"Worker process is {process_status}; raw task status remains {status}."
        )
    elif status in RUNNING and not live:
        task["display_status"] = "STALE_EXECUTING"
        task["status_note"] = "No fresh worker heartbeat; raw task status is stale."
    else:
        task["display_status"] = status
        task["status_note"] = ""
    task["console_group"] = _console_group(status, str(task.get("display_status") or ""), live)
    return task


def _console_group(status: str, display_status: str, live: bool) -> str:
    if status in APPROVAL_WAITING:
        return "approval"
    if status in TERMINAL_FAILED or display_status in PROCESS_FAILED_DISPLAY:
        return "failed"
    if status in RUNNING and live:
        return "running"
    if status in QUEUED:
        return "queued"
    return "none"


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


def _read_control_json(run_dir: Any, name: str) -> dict[str, Any]:
    if not run_dir:
        return {}
    path = Path(str(run_dir)) / "control" / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _control_heartbeat_live(heartbeat: dict[str, Any]) -> bool:
    status = str(heartbeat.get("status") or "")
    if status.lower() not in PROCESS_RUNNING and status.upper() not in RUNNING:
        return False
    ts = _parse_ts(heartbeat.get("last_seen") or heartbeat.get("ts"))
    return ts is not None and time.time() - ts <= HEARTBEAT_FRESH_SECONDS


def _metric_date(created_at: str) -> str:
    if not created_at:
        return "unknown"
    return created_at[:10]


def _session_label(task_id: str) -> str:
    return task_id[-8:] if len(task_id) > 8 else task_id


def _auto_dismiss_superseded_stale_running_tasks(
    db: TaskDB,
    tasks: list[dict[str, Any]],
    live_task_ids: set[str],
) -> None:
    dismissed = db.list_console_dismissed_task_ids()
    latest_success_by_project: dict[str, str] = {}
    for task in tasks:
        status = str(task.get("status") or "")
        if status not in TERMINAL_SUCCESS:
            continue
        project_id = str(task.get("project_id") or "")
        updated_at = str(task.get("updated_at") or "")
        if updated_at >= latest_success_by_project.get(project_id, ""):
            latest_success_by_project[project_id] = updated_at

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if not task_id or task_id in dismissed or task_id in live_task_ids:
            continue
        status = str(task.get("status") or "")
        if status not in RUNNING:
            continue
        project_id = str(task.get("project_id") or "")
        completed_at = latest_success_by_project.get(project_id)
        if not completed_at or completed_at < str(task.get("updated_at") or ""):
            continue
        reason = "superseded by completed task in same project"
        db.dismiss_console_task(task_id, now, reason=reason)
        db.append_event(
            task_id,
            "console.task_auto_dismissed",
            status,
            status,
            {"reason": reason, "completed_at": completed_at},
            at=now,
        )


def _content_type(relative: str) -> str:
    if relative.endswith(".json"):
        return "application/json; charset=utf-8"
    if relative.endswith(".patch"):
        return "text/x-diff; charset=utf-8"
    return "text/plain; charset=utf-8"
