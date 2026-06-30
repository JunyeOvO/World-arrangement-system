from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .db import TaskDB
from .outcomes import derive_task_outcome


class TaskOutcomeRecorder:
    """Records task quality outcomes from DB rows and terminal artifacts."""

    def __init__(self, *, db: TaskDB, artifacts: ArtifactStore) -> None:
        self.db = db
        self.artifacts = artifacts

    def record_task_outcome(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        run_dir = Path(str(task.get("run_dir") or ""))
        task_artifact = read_json_if_exists(run_dir / "task.json") or {}
        verify = read_json_if_exists(run_dir / "verify" / "verify.json") or {}
        review = read_json_if_exists(run_dir / "review" / "review.json") or {}
        result = read_json_if_exists(run_dir / "result.json") or {}
        outcome = derive_task_outcome(
            task,
            metrics=self.db.list_task_metrics(task_id),
            task_artifact=task_artifact if isinstance(task_artifact, dict) else {},
            verify=verify if isinstance(verify, dict) else {},
            review=review if isinstance(review, dict) else {},
            result=result if isinstance(result, dict) else {},
            metadata=metadata,
        )
        self.db.upsert_task_outcome(outcome)
        self.artifacts.write_json(task_id, "outcome.json", outcome)


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"unreadable": str(path)}
