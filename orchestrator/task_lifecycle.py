from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .db import TaskDB
from .outcomes import should_record_outcome


class TaskLifecycleController:
    """Coordinates task status transitions, event writes, and terminal outcome hooks."""

    def __init__(
        self,
        db: TaskDB,
        *,
        now: Callable[[], str],
        sync_task_artifact: Callable[[str], None],
        record_task_outcome: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.db = db
        self.now = now
        self.sync_task_artifact = sync_task_artifact
        self.record_task_outcome = record_task_outcome

    def set_status(self, task_id: str, status: str, event_type: str, payload: dict[str, Any]) -> None:
        old = self.db.get_task(task_id)
        old_status = old["status"] if old else None
        self.db.update_task(task_id, status=status, updated_at=self.now())
        self.sync_task_artifact(task_id)
        self.db.append_event(task_id, event_type, old_status, status, payload)
        if should_record_outcome(status):
            self.record_task_outcome(task_id, {"event_type": event_type})
