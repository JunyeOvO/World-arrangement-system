from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.artifacts import ArtifactStore
from orchestrator.dashboard_status import (
    ACTIVE_STATUSES,
    DONE_STATUSES,
    compute_top_status_counts,
    derive_dashboard_status,
)
from orchestrator.db import TaskDB

from .display_names import display_agent_name, display_model_name, display_route_tree
from .alerts import evaluate_alerts
from .pricing import calculate_token_cost_usd, has_price
from .serializers import (
    alert_view,
    artifact_allowed,
    artifact_listing,
    event_view,
    heartbeat_view,
    metric_view,
    task_summary,
)


HEARTBEAT_FRESH_SECONDS = 120
PROCESS_RUNNING = {"running"}
CONSOLE_GROUP_DESCRIPTIONS = {
    "running": "Fresh worker heartbeat/control heartbeat exists; this is actively executing now.",
    "queued": "Task is accepted and can continue without user input, but no worker is currently live.",
    "failed": "Task or worker reached a failure state that needs retry, dismissal, or investigation.",
    "approval": "Task is paused for user approval, user input, or policy decision; NEEDS_USER belongs here.",
    "alerts": "System-level or runtime-derived anomalies such as stale workers, stuck retry, or unknown statuses.",
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
        counts = compute_top_status_counts(tasks, system_alert_count=len(alerts))
        return {
            "health": {
                "status": "alerting" if counts["alerts"] else "healthy",
                "running": counts["running"],
                "queued": counts["queued"],
                "failed": counts["failed"],
                "approval_waiting": counts["approval_waiting"],
                "open_alerts": counts["alerts"],
                "cost_today_usd": metrics["total_cost_usd"],
            },
            "tasks": tasks,
            "alerts": alerts,
            "heartbeats": heartbeats,
            "metrics": metrics,
            "models": self.model_metrics(),
        }

    def dashboard_summary(self, project_id: str | None = None, include_completed: bool = False) -> dict[str, Any]:
        snapshot = self.snapshot()
        tasks = snapshot["tasks"]
        if project_id:
            tasks = [task for task in tasks if task.get("project_id") == project_id]
        if not include_completed:
            tasks = [task for task in tasks if task.get("console_group") != "none"]
        counts = compute_top_status_counts(tasks, system_alert_count=len(snapshot["alerts"]))
        return {
            "counts": {
                "Running": counts["running"],
                "Queued": counts["queued"],
                "Failed": counts["failed"],
                "Approval": counts["approval_waiting"],
                "Alerts": counts["alerts"],
            },
            "updated_at": _now(),
        }

    def dashboard_tasks(
        self,
        big_status: str | None = None,
        limit: int = 50,
        project_id: str | None = None,
        include_completed: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        normalized_big_status = _normalize_big_status(big_status)
        items: list[dict[str, Any]] = []
        for task in snapshot["tasks"]:
            if project_id and task.get("project_id") != project_id:
                continue
            if not include_completed and task.get("console_group") == "none":
                continue
            if normalized_big_status and task.get("big_status") != normalized_big_status:
                continue
            items.append({
                "task_id": task.get("task_id"),
                "raw_status": task.get("raw_status") or task.get("status"),
                "display_status": task.get("display_status"),
                "big_status": task.get("big_status"),
                "project_id": task.get("project_id"),
                "goal": task.get("user_goal"),
                "reason": task.get("status_reason"),
                "updated_at": task.get("updated_at"),
            })
            if len(items) >= limit:
                break
        return {"items": items, "next_cursor": None}

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
            "route_decision": display_route_tree(route),
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
        rows = self._metric_rows()
        total = sum(calculate_token_cost_usd(row) for row in rows)
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
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self._metric_rows():
            worker = display_agent_name(row.get("worker"))
            model = display_model_name(row.get("model"))
            key = (str(worker or ""), str(model or ""))
            item = grouped.setdefault(key, {
                "worker": worker,
                "model": model,
                "attempts": 0,
                "total_cost_usd": 0.0,
                "successes": 0,
            })
            item["attempts"] += 1
            item["total_cost_usd"] += calculate_token_cost_usd(row)
            if str(row.get("status") or "") in {"success", "COMPLETED_WITH_PATCH", "PR_CREATED", "DONE"}:
                item["successes"] += 1
        summary = []
        for item in grouped.values():
            attempts = int(item["attempts"] or 0)
            avg_cost = (float(item["total_cost_usd"]) / attempts) if attempts else 0.0
            summary.append({
                "worker": item["worker"],
                "model": item["model"],
                "attempts": attempts,
                "avg_cost_usd": round(avg_cost, 6),
                "success_rate": (float(item["successes"]) / attempts) if attempts else 0.0,
                "total_cost_usd": round(float(item["total_cost_usd"]), 6),
            })
        summary.sort(key=lambda row: (-int(row["attempts"]), str(row["model"])))
        return summary

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

    def metrics_efficiency(self, reference_model: str = "opencode-go/glm-5.2") -> dict[str, Any]:
        rows = self._metric_rows()
        total_input = sum(_metric_int(row.get("input_tokens")) for row in rows)
        total_output = sum(_metric_int(row.get("output_tokens")) for row in rows)
        total_cache = sum(_metric_int(row.get("cache_read_input_tokens")) for row in rows)
        total_tokens = total_input + total_output + total_cache
        missing_token_rows = sum(1 for row in rows if _tokens_missing(row))
        priced_rows = [row for row in rows if has_price(row.get("model"))]
        actual_cost = sum(calculate_token_cost_usd(row) for row in rows)
        baseline_cost = sum(calculate_token_cost_usd(row, reference_model) for row in rows)
        savings = baseline_cost - actual_cost
        cache_denominator = total_input + total_cache
        by_model: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            worker = display_agent_name(row.get("worker"))
            model = display_model_name(row.get("model"))
            key = (str(worker or ""), str(model or ""))
            item = by_model.setdefault(key, {
                "worker": worker,
                "model": model,
                "attempts": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "actual_cost_usd": 0.0,
                "reference_cost_usd": 0.0,
            })
            item["attempts"] += 1
            item["input_tokens"] += _metric_int(row.get("input_tokens"))
            item["output_tokens"] += _metric_int(row.get("output_tokens"))
            item["cache_read_input_tokens"] += _metric_int(row.get("cache_read_input_tokens"))
            item["actual_cost_usd"] += calculate_token_cost_usd(row)
            item["reference_cost_usd"] += calculate_token_cost_usd(row, reference_model)
        model_rows = []
        for item in by_model.values():
            item_total_tokens = (
                int(item["input_tokens"])
                + int(item["output_tokens"])
                + int(item["cache_read_input_tokens"])
            )
            item_actual = float(item["actual_cost_usd"])
            item_reference = float(item["reference_cost_usd"])
            model_rows.append({
                "worker": item["worker"],
                "model": item["model"],
                "attempts": item["attempts"],
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "cache_read_input_tokens": item["cache_read_input_tokens"],
                "total_tokens": item_total_tokens,
                "actual_cost_usd": round(item_actual, 6),
                "reference_cost_usd": round(item_reference, 6),
                "savings_usd": round(item_reference - item_actual, 6),
            })
        model_rows.sort(key=lambda row: (-float(row["savings_usd"]), str(row["model"])))
        return {
            "attempts": len(rows),
            "priced_attempts": len(priced_rows),
            "missing_token_rows": missing_token_rows,
            "reference_model": display_model_name(reference_model),
            "actual_cost_usd": round(actual_cost, 6),
            "reference_cost_usd": round(baseline_cost, 6),
            "savings_usd": round(savings, 6),
            "savings_pct": round((savings / baseline_cost) * 100, 2) if baseline_cost > 0 else 0.0,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cache_read_input_tokens": total_cache,
            "total_tokens": total_tokens,
            "cache_read_ratio": round((total_cache / cache_denominator) * 100, 2)
            if cache_denominator > 0 else 0.0,
            "codex_token_savings_measured": False,
            "codex_token_savings_note": (
                "World records worker token usage and computed model cost. It does not yet record a "
                "same-task no-World Codex baseline, so Codex token savings are an inferred capability, "
                "not a measured metric."
            ),
            "by_model": model_rows,
        }

    def _metric_rows(self) -> list[dict[str, Any]]:
        tasks = self.db.list_tasks(limit=500)
        rows: list[dict[str, Any]] = []
        for task in tasks:
            rows.extend(self.db.list_task_metrics(task["task_id"]))
        return rows

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
    heartbeat_fresh = status in ACTIVE_STATUSES and (task_id in live_task_ids or control_live)
    dashboard_status = derive_dashboard_status(
        raw,
        heartbeat_fresh=heartbeat_fresh,
        control_process=process,
    )
    runtime: dict[str, Any] = {
        "live": dashboard_status.is_live,
        "stale": dashboard_status.is_stale,
    }
    process_status = str(process.get("status") or "")
    process_finished = bool(process_status or process.get("finished_at"))
    if process_status:
        runtime["process_status"] = process_status
        runtime["process_finished"] = process_finished
    control_heartbeat_status = str(control_heartbeat.get("status") or "")
    if control_heartbeat_status:
        runtime["control_heartbeat_status"] = control_heartbeat_status
        runtime["control_heartbeat_live"] = control_live
    task["runtime"] = runtime
    task["raw_status"] = dashboard_status.raw_status
    task["display_status"] = dashboard_status.display_status
    task["big_status"] = dashboard_status.big_status
    task["console_group"] = dashboard_status.console_group
    task["is_terminal"] = dashboard_status.is_terminal
    task["requires_user_action"] = dashboard_status.requires_user_action
    task["status_reason"] = dashboard_status.reason
    task["status_note"] = "" if dashboard_status.display_status == status else dashboard_status.reason
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
        if status not in ACTIVE_STATUSES and phase not in ACTIVE_STATUSES:
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
    if status.lower() not in PROCESS_RUNNING and status.upper() not in ACTIVE_STATUSES:
        return False
    ts = _parse_ts(heartbeat.get("last_seen") or heartbeat.get("ts"))
    return ts is not None and time.time() - ts <= HEARTBEAT_FRESH_SECONDS


def _metric_date(created_at: str) -> str:
    if not created_at:
        return "unknown"
    return created_at[:10]


def _metric_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _tokens_missing(row: dict[str, Any]) -> bool:
    return (
        row.get("input_tokens") is None
        and row.get("output_tokens") is None
        and row.get("cache_read_input_tokens") is None
    )


def _session_label(task_id: str) -> str:
    return task_id[-8:] if len(task_id) > 8 else task_id


def _normalize_big_status(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "running": "Running",
        "queued": "Queued",
        "failed": "Failed",
        "approval": "Approval",
        "alerts": "Alerts",
        "done": "Done",
        "closed": "Closed",
    }
    return mapping.get(normalized, value)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _auto_dismiss_superseded_stale_running_tasks(
    db: TaskDB,
    tasks: list[dict[str, Any]],
    live_task_ids: set[str],
) -> None:
    dismissed = db.list_console_dismissed_task_ids()
    latest_success_by_project: dict[str, str] = {}
    for task in tasks:
        status = str(task.get("status") or "")
        if status not in DONE_STATUSES:
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
        if status not in ACTIVE_STATUSES:
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
