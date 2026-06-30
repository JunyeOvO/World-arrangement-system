from __future__ import annotations

from typing import Any

from .db import TaskDB
from .permissions import check_write_paths


class WorkerPermissionAuditor:
    """Audits worker write permissions and records permission events."""

    def __init__(self, db: TaskDB) -> None:
        self.db = db

    def check_declared_permissions(
        self,
        task_id: str,
        worker_name: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        paths = declared_write_paths(task)
        review = check_write_paths(worker_name, paths).to_dict()
        task_row = self.db.get_task(task_id)
        status = task_row["status"] if task_row else None
        self.db.append_event(
            task_id,
            "permission_preflight",
            status,
            status,
            {"worker": worker_name, "paths": paths, "permission": review},
        )
        return review

    def check_diff_permissions(
        self,
        task_id: str,
        worker_name: str,
        changed_files: list[str],
    ) -> dict[str, Any]:
        checked_files = changed_files or []
        review = check_write_paths(worker_name, checked_files).to_dict()
        event_type = "permission_denied" if not review["allowed"] else "permission_diff_checked"
        task_row = self.db.get_task(task_id)
        status = task_row["status"] if task_row else None
        self.db.append_event(
            task_id,
            event_type,
            status,
            status,
            {"worker": worker_name, "changed_files": checked_files, "permission": review},
        )
        return review


def declared_write_paths(task: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("owned_paths", "target_paths", "planned_files"):
        value = task.get(key)
        if isinstance(value, list):
            paths.extend(str(item) for item in value if item)
    return list(dict.fromkeys(paths))
