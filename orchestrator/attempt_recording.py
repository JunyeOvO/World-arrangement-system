from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import TaskDB
from .metrics import collect_task_metrics, write_metrics
from .token_ledger import write_task_token_ledger


class AttemptMetricsRecorder:
    """Records attempt-level metrics and refreshes the per-task token ledger."""

    def __init__(self, db: TaskDB) -> None:
        self.db = db

    def write_attempt_metrics(
        self,
        task_id: str,
        attempt_no: int,
        attempt: dict[str, Any],
        worker_result: Any,
        failure: Any | None,
        build_passed: bool | None = None,
        review_approved: bool | None = None,
    ) -> None:
        task = self.db.get_task(task_id)
        if not task or not task.get("run_dir"):
            return
        run_dir = Path(str(task["run_dir"]))
        metrics = collect_task_metrics(
            task_id=task_id,
            attempt_no=attempt_no,
            worker=str(attempt.get("worker", "")),
            model=str(attempt.get("model", "")),
            status=str(getattr(worker_result, "status", "")),
            stream_path=getattr(worker_result, "stdout_path", None),
            changed_files_count=len(getattr(worker_result, "changed_files", []) or []),
            failure_reason=failure.failure_reason if failure else None,
            build_passed=build_passed,
            review_approved=review_approved,
            **memory_metric_kwargs(read_task_artifact(run_dir)),
        )
        write_metrics(metrics, run_dir / "attempts" / f"{attempt_no:02d}" / "metrics.json")
        write_metrics(metrics, run_dir / "metrics.json")
        self.db.upsert_task_metrics(metrics.to_dict())
        self.write_token_ledger(task_id)

    def write_token_ledger(self, task_id: str) -> None:
        task = self.db.get_task(task_id)
        if not task or not task.get("run_dir"):
            return
        write_task_token_ledger(self.db, task_id, Path(str(task["run_dir"])) / "token_ledger.json")

    def write_repaired_result_metrics(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        stdout_path: Path,
        verify: dict[str, Any],
        review: dict[str, Any],
    ) -> None:
        task_id = str(task["task_id"])
        run_dir = Path(str(task["run_dir"]))
        metrics = collect_task_metrics(
            task_id=task_id,
            attempt_no=1,
            worker=str(task.get("route_worker") or "opencode"),
            model=str(task.get("route_model") or "opencode_go_glm52"),
            status=str(result.get("status") or ""),
            stream_path=str(stdout_path),
            changed_files_count=len(result.get("changed_files") or []),
            build_passed=verify.get("build_passed"),
            review_approved=review.get("approved"),
            **memory_metric_kwargs(task),
        )
        write_metrics(metrics, run_dir / "attempts" / "01" / "metrics.json")
        write_metrics(metrics, run_dir / "metrics.json")
        self.db.upsert_task_metrics(metrics.to_dict())
        self.write_token_ledger(task_id)


def read_task_artifact(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "task.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def memory_metric_kwargs(task: dict[str, Any]) -> dict[str, int | None]:
    payload = task.get("project_memory")
    if not isinstance(payload, dict):
        return {"memory_hit_count": None, "memory_miss_count": None}
    memory = payload.get("memory")
    if not isinstance(memory, dict):
        return {"memory_hit_count": None, "memory_miss_count": None}
    stats = memory.get("stats")
    if not isinstance(stats, dict):
        return {"memory_hit_count": None, "memory_miss_count": None}
    return {
        "memory_hit_count": _int_or_none(stats.get("hit_count")),
        "memory_miss_count": _int_or_none(stats.get("miss_count")),
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
