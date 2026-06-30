from __future__ import annotations

from typing import Any

from .db import TaskDB
from .policy_update_engine import PolicyUpdateEngine


class PolicyLearningRecorder:
    """Records task outcomes into the policy learning engine."""

    def __init__(self, db: TaskDB) -> None:
        self.db = db

    def record_task_completion(
        self,
        task: dict[str, Any],
        project: dict[str, Any],
        success: bool,
        worker: str = "",
        model: str = "",
        variant: str = "",
        tests_passed: bool = False,
        codex_review_approved: bool = False,
        pr_created: bool = False,
        rollback: bool = False,
        incident: bool = False,
        changed_paths: list[str] | None = None,
    ) -> None:
        engine = PolicyUpdateEngine(self.db)
        engine.on_task_complete(
            task_id=task["task_id"],
            project_id=task["project_id"],
            task_type=task.get("task_type", "routine_coding"),
            risk_level=task.get("risk_level", "medium"),
            approval_mode=task.get("status", "UNKNOWN"),
            worker=worker,
            model=model,
            variant=variant,
            planned_files_count=len(changed_paths or []),
            actual_files_count=len(changed_paths or []),
            changed_paths=changed_paths or [],
            tests_passed=tests_passed,
            codex_review_approved=codex_review_approved,
            pr_created=pr_created,
            rollback=rollback,
            incident=incident,
        )
