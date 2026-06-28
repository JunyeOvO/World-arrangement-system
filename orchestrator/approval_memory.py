"""Approval Memory — records outcomes and updates learned patterns.

Only learns from real outcomes (user decisions, PR merges, rollbacks, test results),
NEVER from model self-assessment.
"""

from __future__ import annotations

import json
import time
from typing import Any


class ApprovalMemory:
    """Records approval events and manages pattern learning."""

    def __init__(self, db):
        self._db = db

    def record_outcome(
        self,
        task_id: str,
        project_id: str,
        task_type: str,
        risk_level: str,
        approval_mode: str,
        worker: str | None = None,
        model: str | None = None,
        variant: str | None = None,
        planned_files_count: int = 0,
        actual_files_count: int = 0,
        changed_paths: list[str] | None = None,
        tests_passed: bool | None = None,
        codex_review_approved: bool | None = None,
        pr_created: bool = False,
        pr_merged: bool = False,
        rollback: bool = False,
        incident: bool = False,
        user_decision: str | None = None,
        user_feedback: str | None = None,
    ) -> None:
        row = {
            "task_id": task_id,
            "project_id": project_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "task_type": task_type,
            "risk_level": risk_level,
            "approval_mode": approval_mode,
            "worker": worker,
            "model": model,
            "variant": variant,
            "planned_files_count": planned_files_count,
            "actual_files_count": actual_files_count,
            "changed_paths_json": json.dumps(changed_paths or []),
            "tests_passed": _bool_or_none(tests_passed),
            "codex_review_approved": _bool_or_none(codex_review_approved),
            "pr_created": pr_created,
            "pr_merged": pr_merged,
            "rollback": rollback,
            "incident": incident,
            "user_decision": user_decision,
            "user_feedback": user_feedback,
        }
        self._db.record_approval_event(row)

    def learn_from_outcome(
        self,
        project_id: str,
        task_type: str,
        path_pattern: str,
        success: bool,
        rollback: bool = False,
        worker: str | None = None,
        model: str | None = None,
        variant: str | None = None,
    ) -> None:
        """Update learned pattern trust score based on a real outcome."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        row = {
            "project_id": project_id,
            "task_type": task_type,
            "path_pattern": path_pattern,
            "worker": worker,
            "model": model,
            "variant": variant,
            "approvals_count": 1,
            "success_count": 1 if success else 0,
            "failure_count": 0 if success else 1,
            "rollback_count": 1 if rollback else 0,
            "trust_score": 0.5,  # will be computed by upsert
            "confidence": 0.1,
            "suggested_mode": _suggested_mode(task_type),
            "active": 1,
            "created_at": now,
            "updated_at": now,
            "expires_at": None,
        }
        self._db.upsert_learned_pattern(row)

    def get_learned_rules(self, project_id: str) -> list[dict[str, Any]]:
        return self._db.get_learned_patterns(project_id, active_only=True)

    def revoke_rule(self, pattern_id: int) -> None:
        self._db.revoke_learned_pattern(pattern_id)

    def suggest_policies(self, project_id: str) -> list[dict[str, Any]]:
        """Generate policy suggestions based on learned patterns with high confidence."""
        patterns = self._db.get_learned_patterns(project_id, active_only=True)
        suggestions = []
        for pat in patterns:
            if pat["confidence"] >= 0.6 and pat["approvals_count"] >= 3:
                if pat["trust_score"] >= 0.8 and pat.get("suggested_mode") != "HARD_APPROVAL":
                    suggestions.append({
                        "pattern_id": pat["id"],
                        "project_id": project_id,
                        "task_type": pat["task_type"],
                        "path_pattern": pat["path_pattern"],
                        "current_trust": pat["trust_score"],
                        "current_confidence": pat["confidence"],
                        "suggested_approval_mode": pat.get("suggested_mode", "AUTO_WITH_SUMMARY"),
                        "reason": f"High trust ({pat['trust_score']:.2f}) after {pat['approvals_count']} approvals for {pat['task_type']}",
                    })
        return suggestions


def _bool_or_none(val: bool | None) -> int | None:
    if val is None:
        return None
    return 1 if val else 0


def _suggested_mode(task_type: str) -> str:
    if task_type in ("docs", "test_generation", "simple_bugfix"):
        return "AUTO_SILENT"
    if task_type in ("routine_coding",):
        return "AUTO_WITH_SUMMARY"
    return "SOFT_APPROVAL"
