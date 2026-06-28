"""Policy Update Engine — generates and manages policy suggestions.

After each task completes, evaluates whether the outcome warrants:
- Elevating trust for a learned pattern
- Generating a new policy suggestion
- Downgrading trust due to failure or rollback
"""

from __future__ import annotations

import json
import time
from typing import Any


class PolicyUpdateEngine:
    """Generates policy suggestions and manages trust score updates."""

    def __init__(self, db):
        self._db = db

    def on_task_complete(
        self,
        task_id: str,
        project_id: str,
        task_type: str,
        risk_level: str,
        approval_mode: str,
        worker: str | None,
        model: str | None,
        variant: str | None,
        planned_files_count: int,
        actual_files_count: int,
        changed_paths: list[str],
        tests_passed: bool,
        codex_review_approved: bool,
        pr_created: bool,
        pr_merged: bool = False,
        rollback: bool = False,
        incident: bool = False,
        user_decision: str | None = None,
        user_feedback: str | None = None,
    ) -> None:
        """Process a completed task and update learned patterns."""
        path_pattern = _derive_path_pattern(changed_paths)
        success = tests_passed and codex_review_approved and not rollback

        from .approval_memory import ApprovalMemory
        mem = ApprovalMemory(self._db)

        # Record the outcome
        mem.record_outcome(
            task_id, project_id, task_type, risk_level, approval_mode,
            worker, model, variant, planned_files_count, actual_files_count,
            changed_paths, tests_passed, codex_review_approved,
            pr_created, pr_merged, rollback, incident,
            user_decision, user_feedback,
        )

        # Update learned pattern
        if path_pattern or task_type:
            mem.learn_from_outcome(
                project_id, task_type,
                path_pattern or f"type:{task_type}",
                success, rollback, worker, model, variant,
            )

    def generate_suggestions(self, project_id: str) -> list[dict[str, Any]]:
        """Generate pending policy suggestions for a project."""
        from .approval_memory import ApprovalMemory
        mem = ApprovalMemory(self._db)
        suggestions = mem.suggest_policies(project_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for s in suggestions:
            self._db.add_policy_suggestion({
                "project_id": project_id,
                "suggestion_json": json.dumps(s),
                "status": "pending",
                "created_at": now,
                "decided_at": None,
            })
        return suggestions

    def approve_suggestion(self, suggestion_id: int, user: str = "codex") -> dict[str, Any]:
        """Approve a policy suggestion and create the corresponding override."""
        suggestions = self._db.get_policy_suggestions("", status="pending")
        target = None
        for s in suggestions:
            if s["id"] == suggestion_id:
                target = s
                break
        if not target:
            return {"error": "suggestion not found", "suggestion_id": suggestion_id}

        body = json.loads(target["suggestion_json"])
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._db.add_policy_override({
            "project_id": body["project_id"],
            "rule_name": f"learned-{body['task_type']}-{body['pattern_id']}",
            "matcher_json": json.dumps({"task_type": body["task_type"]}),
            "approval_mode": body["suggested_approval_mode"],
            "created_by": user,
            "created_at": now,
            "expires_at": None,
            "active": 1,
        })
        self._db.update_policy_suggestion(suggestion_id, "approved", now)
        return {"status": "approved", "suggestion_id": suggestion_id}

    def reject_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """Reject a policy suggestion."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._db.update_policy_suggestion(suggestion_id, "rejected", now)
        return {"status": "rejected", "suggestion_id": suggestion_id}


def _derive_path_pattern(changed_paths: list[str]) -> str:
    """Derive a path pattern from changed files for learning."""
    if not changed_paths:
        return ""
    # Use the most common directory prefix
    from collections import Counter
    dirs = []
    for p in changed_paths:
        parts = p.replace("\\", "/").split("/")
        if len(parts) > 1:
            dirs.append("/".join(parts[:-1]) + "/**")
        else:
            dirs.append(p)
    if dirs:
        most_common = Counter(dirs).most_common(1)[0][0]
        return most_common
    return changed_paths[0] if changed_paths else ""
