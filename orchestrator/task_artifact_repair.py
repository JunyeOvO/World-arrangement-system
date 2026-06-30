from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .attempt_recording import AttemptMetricsRecorder
from .db import TaskDB
from .read_only_completion import extract_worker_success_text
from .task_result_document import build_final_markdown


class TaskArtifactRepairService:
    """Repairs run artifacts that can be derived from DB state or worker streams."""

    def __init__(
        self,
        *,
        db: TaskDB,
        artifacts: ArtifactStore,
        metrics_recorder: AttemptMetricsRecorder,
        extract_success_text: Callable[[Path], str | None] = extract_worker_success_text,
    ) -> None:
        self.db = db
        self.artifacts = artifacts
        self.metrics_recorder = metrics_recorder
        self.extract_success_text = extract_success_text

    def repair_task_artifacts(self, task_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        """Conservatively repair artifacts without inferring new task states."""
        if task_id:
            task = self.db.get_task(task_id)
            tasks = [task] if task else []
        else:
            tasks = self.db.list_tasks(limit=limit)
        repaired: list[dict[str, Any]] = []
        for task in tasks:
            if not task:
                continue
            changes: list[str] = []
            if self.sync_task_artifact_from_db(str(task["task_id"])):
                changes.append("task_json_synced")
            if self.repair_worker_result_artifacts(task):
                changes.append("worker_result_backfilled")
            if changes:
                repaired.append({"task_id": task["task_id"], "changes": changes})
        return {
            "status": "ok",
            "scope": task_id or f"recent:{max(1, min(int(limit), 500))}",
            "repaired_count": len(repaired),
            "repaired": repaired,
        }

    def sync_task_artifact_from_db(self, task_id: str) -> bool:
        task = self.db.get_task(task_id)
        if not task:
            return False
        task_path = Path(str(task.get("run_dir") or "")) / "task.json"
        if not task_path.exists():
            return False
        payload = read_json_if_exists(task_path)
        if not isinstance(payload, dict):
            return False
        changed = False
        for key in (
            "status",
            "updated_at",
            "route_worker",
            "route_model",
            "route_variant",
            "pr_url",
        ):
            value = task.get(key)
            if value is not None and payload.get(key) != value:
                payload[key] = value
                changed = True
        if changed:
            self.artifacts.write_json(task_id, "task.json", payload)
        return changed

    def repair_worker_result_artifacts(self, task: dict[str, Any]) -> bool:
        if str(task.get("route_worker") or "") != "opencode":
            return False
        run_dir = Path(str(task.get("run_dir") or ""))
        result_path = run_dir / "result.json"
        result = read_json_if_exists(result_path)
        if not isinstance(result, dict):
            return False
        stdout_path = Path(str(result.get("stdout_path") or run_dir / "worker" / "worker.stdout.jsonl"))
        summary = self.extract_success_text(stdout_path)
        if not summary:
            return False
        current_summary = str(result.get("summary") or "")
        generic_summary = current_summary.strip() in {"", "OpenCode worker finished", "OpenCode worker failed"}
        if not generic_summary:
            return False
        result["summary"] = summary
        task_id = str(task["task_id"])
        self.artifacts.write_json(task_id, "result.json", result)
        attempt_result = run_dir / "attempts" / "01" / "result.json"
        attempt_payload = read_json_if_exists(attempt_result)
        if isinstance(attempt_payload, dict):
            attempt_payload["summary"] = summary
            self.artifacts.write_json(task_id, "attempts/01/result.json", attempt_payload)
        route = read_json_if_exists(run_dir / "route.json") or {
            "selected_worker": task.get("route_worker") or "opencode",
            "selected_model": task.get("route_model") or "opencode_go_glm52",
        }
        verify = read_json_if_exists(run_dir / "verify" / "verify.json") or {}
        review = read_json_if_exists(run_dir / "review" / "review.json") or {}
        self.artifacts.write_text(task_id, "final.md", build_final_markdown(task, route, result, verify, review))
        self.metrics_recorder.write_repaired_result_metrics(task, result, stdout_path, verify, review)
        return True


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"unreadable": str(path)}
