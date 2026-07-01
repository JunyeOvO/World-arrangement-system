from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .baselines import build_manual_baseline, build_replay_baseline
from .db import TaskDB
from .process_control import request_cancel
from .state_machine import can_transition
from .task_artifact_repair import TaskArtifactRepairService


class TaskOperationsService:
    """Owns task query/control operations outside the execution pipeline."""

    RESULT_ARTIFACTS = [
        "final.md",
        "review/review.json",
        "verify/verify.json",
        "verify/diff.patch",
        "metrics.json",
        "token_ledger.json",
        "multimodal/vision_observation.json",
        "result.json",
    ]

    def __init__(
        self,
        *,
        db: TaskDB,
        artifacts: ArtifactStore,
        artifact_repair: TaskArtifactRepairService,
        reap_stale_worker_task: Callable[[dict[str, Any]], None],
        record_policy_learning: Callable[..., None],
        write_token_ledger: Callable[[str], None],
        now: Callable[[], str],
    ) -> None:
        self.db = db
        self.artifacts = artifacts
        self.artifact_repair = artifact_repair
        self.reap_stale_worker_task = reap_stale_worker_task
        self.record_policy_learning = record_policy_learning
        self.write_token_ledger = write_token_ledger
        self.now = now

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        task = self._refresh_after_reap(task)
        events = self.db.list_events(task_id)
        return {**task, "events": events[-10:]}

    def read_task_result(self, task_id: str, sections: list[str] | None = None) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        task = self._refresh_after_reap(task)
        index = self.artifacts.index(task_id)
        result: dict[str, Any] = {"task": task, "artifacts": index}
        base = Path(str(task["run_dir"])).resolve() if task.get("run_dir") else None
        for key in self.RESULT_ARTIFACTS:
            path = index.get(key)
            if not path or base is None:
                continue
            target = Path(path).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                result[key] = "[artifact escaped run directory]"
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
            result[key] = text[:20000]
        return result

    def record_task_baseline(
        self,
        task_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        actual: bool = False,
        baseline_kind: str | None = None,
    ) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if input_tokens is not None or output_tokens is not None:
            if input_tokens is None or output_tokens is None:
                return {"status": "INVALID_REQUEST", "error": "input_tokens and output_tokens must be provided together"}
            baseline = build_manual_baseline(
                task_id=task_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                baseline_kind=baseline_kind or ("codex_only_actual" if actual else "codex_only_manual_estimate"),
                actual_codex_used=actual,
                metadata={"source": "cli_record_task_baseline"},
            )
        else:
            baseline = build_replay_baseline(
                task=task,
                artifact_index=self.artifacts.index(task_id),
                baseline_kind=baseline_kind or "codex_only_replay",
            )
        self.artifacts.append_jsonl(task_id, "baselines/task_baselines.jsonl", baseline)
        self.db.record_task_baseline(baseline)
        self.db.append_event(
            task_id,
            "task_baseline_recorded",
            None,
            None,
            {
                "baseline_kind": baseline.get("baseline_kind"),
                "source": baseline.get("source"),
                "total_tokens": baseline.get("total_tokens"),
                "actual_codex_used": bool(baseline.get("actual_codex_used")),
            },
        )
        self.write_token_ledger(task_id)
        return {
            "status": "BASELINE_RECORDED",
            "task_id": task_id,
            "baseline": baseline,
            "token_ledger_path": str(Path(str(task["run_dir"])) / "token_ledger.json") if task.get("run_dir") else None,
        }

    def repair_task_artifacts(self, task_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return self.artifact_repair.repair_task_artifacts(task_id, limit)

    def open_task_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        return {"task_id": task_id, "run_dir": task["run_dir"], "files": self.artifacts.index(task_id)}

    def get_task_control(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        task = self._refresh_after_reap(task)
        control_dir = Path(task["run_dir"]) / "control"
        return {
            "task_id": task_id,
            "task_status": task["status"],
            "run_dir": task["run_dir"],
            "control_dir": str(control_dir),
            "process": _read_json_if_exists(control_dir / "process.json"),
            "heartbeat": _read_json_if_exists(control_dir / "heartbeat.json"),
            "cancel_requested": _read_json_if_exists(control_dir / "cancel.requested"),
        }

    def cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if not can_transition(str(task.get("status") or ""), "CANCELLED"):
            return {
                "status": "INVALID_STATE",
                "task_id": task_id,
                "from_state": task.get("status"),
                "to_state": "CANCELLED",
                "reason": "cancel is not allowed from current state",
            }
        control = request_cancel(Path(task["run_dir"]), reason)
        self.db.update_task(task_id, status="CANCELLED", updated_at=self.now())
        self.db.append_event(
            task_id,
            "cancelled",
            task["status"],
            "CANCELLED",
            {"reason": reason, "control": control},
        )
        return self.get_task_status(task_id)

    def rollback_task(self, task_id: str, cleanup_worktree: bool = True) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if not can_transition(str(task.get("status") or ""), "ROLLED_BACK"):
            return {
                "status": "INVALID_STATE",
                "task_id": task_id,
                "from_state": task.get("status"),
                "to_state": "ROLLED_BACK",
                "reason": "rollback is not allowed from current state",
            }
        self.db.update_task(task_id, status="ROLLED_BACK", updated_at=self.now())
        self.db.append_event(task_id, "rolled_back", task["status"], "ROLLED_BACK", {"cleanup_worktree": cleanup_worktree})
        self.record_policy_learning(
            task,
            {},
            success=False,
            worker=task.get("route_worker", ""),
            model=task.get("route_model", ""),
            rollback=True,
        )
        return self.get_task_status(task_id)

    def _refresh_after_reap(self, task: dict[str, Any]) -> dict[str, Any]:
        self.reap_stale_worker_task(task)
        return self.db.get_task(task["task_id"]) or task


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"unreadable": str(path)}
