from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

from orchestrator.scheduler import OrchestratorService
from orchestrator.state_machine import can_transition

from .queries import ConsoleQueries
from .redaction import redact


ALLOWED_ACTIONS = {"cancel", "retry", "approve", "reject", "resolve_alert"}
RETRYABLE_STATES = {"FAILED", "FAILED_FINAL", "CANCELLED", "DONE_WITH_BLOCK", "COMPLETED_WITH_PATCH"}
APPROVAL_STATES = {"HARD_APPROVAL_WAITING", "SOFT_APPROVAL_WAITING", "NEEDS_USER", "BLOCKED"}
DISMISSIBLE_STATES = {"FAILED", "FAILED_FINAL"} | APPROVAL_STATES


class ConsoleAPI:
    def __init__(self, service: OrchestratorService | None = None):
        self.service = service or OrchestratorService()
        self.queries = ConsoleQueries(self.service.db, self.service.artifacts)

    def handle_get(self, path: str, query: str = "") -> tuple[int, str, Any]:
        params = {key: values[-1] for key, values in parse_qs(query).items() if values}
        if path == "/api/console/snapshot":
            return 200, "application/json", self.queries.snapshot()
        if path == "/api/tasks":
            return 200, "application/json", self.queries.list_tasks(
                params.get("status"),
                params.get("project_id"),
                _int(params.get("limit"), 100),
            )
        if path.startswith("/api/tasks/"):
            return self._handle_task_get(path)
        if path == "/api/metrics/summary":
            return 200, "application/json", self.queries.metrics_summary()
        if path == "/api/metrics/models":
            return 200, "application/json", {"models": self.queries.model_metrics()}
        if path == "/api/audit":
            return 200, "application/json", self.queries.audit(
                params.get("task_id"),
                params.get("action"),
                _int(params.get("limit"), 100),
            )
        if path == "/api/alerts":
            return 200, "application/json", self.queries.alerts(params.get("status", "open"))
        if path == "/api/config/effective":
            return 200, "application/json", self.queries.config_effective(params.get("project_id"))
        return 404, "application/json", {"status": "NOT_FOUND"}

    def handle_post(self, path: str, body: bytes) -> tuple[int, str, Any]:
        payload = _json_body(body)
        if "/cancel" in path and path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            return self._cancel(task_id, str(payload.get("reason") or "console cancel"))
        if "/retry" in path and path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            return self._retry(task_id)
        if "/dismiss" in path and path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            return self._dismiss(task_id, str(payload.get("reason") or "console dismissed"))
        if path.startswith("/api/approvals/") and path.endswith("/approve"):
            return self._approval(path.split("/")[3], "approve", payload)
        if path.startswith("/api/approvals/") and path.endswith("/reject"):
            return self._approval(path.split("/")[3], "reject", payload)
        if path.startswith("/api/alerts/") and path.endswith("/resolve"):
            alert_id = path.split("/")[3]
            return self._resolve_alert(alert_id)
        return 404, "application/json", {"status": "NOT_FOUND"}

    def _handle_task_get(self, path: str) -> tuple[int, str, Any]:
        parts = path.split("/")
        task_id = parts[3] if len(parts) > 3 else ""
        if len(parts) == 4:
            detail = self.queries.task_detail(task_id)
            return (404 if detail.get("status") == "NOT_FOUND" else 200), "application/json", detail
        if len(parts) == 5 and parts[4] == "timeline":
            return 200, "application/json", self.queries.task_timeline(task_id)
        if len(parts) == 5 and parts[4] == "artifacts":
            return 200, "application/json", self.queries.task_artifacts(task_id)
        if len(parts) >= 6 and parts[4] == "artifacts":
            relative = "/".join(parts[5:])
            return self.queries.read_artifact_text(task_id, relative)
        return 404, "application/json", {"status": "NOT_FOUND"}

    def _cancel(self, task_id: str, reason: str) -> tuple[int, str, Any]:
        task = self.service.db.get_task(task_id)
        if not task:
            return 404, "application/json", {"status": "NOT_FOUND", "task_id": task_id}
        if not can_transition(str(task["status"]), "CANCELLED"):
            return 409, "application/json", {"status": "INVALID_STATE", "task_id": task_id, "action": "cancel"}
        result = self.service.cancel_task(task_id, reason=reason)
        self.service.db.append_event(task_id, "console.cancel_clicked", task["status"], "CANCELLED", {"reason": reason})
        return 200, "application/json", result

    def _retry(self, task_id: str) -> tuple[int, str, Any]:
        task = self.service.db.get_task(task_id)
        if not task:
            return 404, "application/json", {"status": "NOT_FOUND", "task_id": task_id}
        if str(task["status"]) not in RETRYABLE_STATES:
            return 409, "application/json", {"status": "INVALID_STATE", "task_id": task_id, "action": "retry"}
        self.service.db.update_task(task_id, status="RETRYING", updated_at=__import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()))
        self.service.db.append_event(task_id, "console.retry_clicked", task["status"], "RETRYING", {})
        return 200, "application/json", self.service.get_task_status(task_id)

    def _approval(self, task_id: str, action: str, payload: dict[str, Any]) -> tuple[int, str, Any]:
        task = self.service.db.get_task(task_id)
        if not task:
            return 404, "application/json", {"status": "NOT_FOUND", "task_id": task_id}
        if str(task["status"]) not in APPROVAL_STATES:
            return 409, "application/json", {"status": "INVALID_STATE", "task_id": task_id, "action": action}
        if action == "approve":
            result = self.service.approve_task(task_id)
            self.service.db.append_event(task_id, "console.approval_submitted", task["status"], task["status"], {"decision": "approved"})
            return 200, "application/json", result
        reason = str(payload.get("reason") or "")
        result = self.service.reject_task(task_id, reason=reason)
        self.service.db.append_event(task_id, "console.approval_submitted", task["status"], "CANCELLED", {"decision": "rejected"})
        return 200, "application/json", result

    def _resolve_alert(self, alert_id: str) -> tuple[int, str, Any]:
        ok = self.service.db.resolve_system_alert(
            alert_id,
            __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        )
        return (200 if ok else 404), "application/json", {"status": "resolved" if ok else "NOT_FOUND", "alert_id": alert_id}

    def _dismiss(self, task_id: str, reason: str) -> tuple[int, str, Any]:
        task = self.service.db.get_task(task_id)
        if not task:
            return 404, "application/json", {"status": "NOT_FOUND", "task_id": task_id}
        if str(task["status"]) not in DISMISSIBLE_STATES:
            return 409, "application/json", {"status": "INVALID_STATE", "task_id": task_id, "action": "dismiss"}
        now = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())
        self.service.db.dismiss_console_task(task_id, now, reason=reason)
        self.service.db.append_event(
            task_id,
            "console.task_dismissed",
            task["status"],
            task["status"],
            {"reason": reason},
            at=now,
        )
        return 200, "application/json", {"status": "dismissed", "task_id": task_id}


def json_response(status: int, payload: Any) -> bytes:
    return json.dumps(redact(payload), ensure_ascii=False, indent=2).encode("utf-8")


def _json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default
