"""Approval and policy facade for scheduler-facing workflows."""

from __future__ import annotations

from typing import Any

from .approval_explainer import explain_decision
from .approval_graph import ApprovalGraph, _classify_task_type
from .approval_memory import ApprovalMemory
from .policy_update_engine import PolicyUpdateEngine


class ApprovalPolicyService:
    """Owns dynamic approval decisions, learned rules, and policy suggestions."""

    def __init__(self, db) -> None:
        self.db = db

    def classify_task_type(self, user_goal: str, project: dict[str, Any] | None = None) -> str:
        return _classify_task_type(user_goal, project or {})

    def decision_for_goal(
        self,
        project_id: str,
        user_goal: str,
        risk_level: str = "medium",
    ) -> dict[str, Any]:
        task = {"user_goal": user_goal, "risk_level": risk_level, "project_id": project_id}
        decision = self.decide(task)
        return {"decision": decision.to_dict(), "explanation": self.explain(decision, task)}

    def decide(self, task: dict[str, Any], project: dict[str, Any] | None = None):
        return ApprovalGraph(self.db).decide(task, project)

    def explain(self, decision, task: dict[str, Any]) -> str:
        return explain_decision(decision, task)

    def approve_task(self, task: dict[str, Any] | None, user: str = "codex") -> dict[str, Any]:
        if not task:
            return {"status": "NOT_FOUND", "task_id": ""}
        self.record_user_decision(task, "approved")
        return {"status": "approved", "task_id": task["task_id"]}

    def reject_task(self, task: dict[str, Any] | None, reason: str = "") -> dict[str, Any]:
        if not task:
            return {"status": "NOT_FOUND", "task_id": ""}
        self.record_user_decision(task, "rejected", reason)
        return {"status": "rejected", "task_id": task["task_id"]}

    def list_learned_rules(self, project_id: str) -> dict[str, Any]:
        rules = ApprovalMemory(self.db).get_learned_rules(project_id)
        from .approval_explainer import explain_learned_rules
        return {"rules": rules, "summary": explain_learned_rules(rules)}

    def revoke_learned_rule(self, pattern_id: int) -> dict[str, Any]:
        ApprovalMemory(self.db).revoke_rule(pattern_id)
        return {"status": "revoked", "pattern_id": pattern_id}

    def explain_task_approval(self, task: dict[str, Any] | None) -> dict[str, Any]:
        if not task:
            return {"status": "NOT_FOUND", "task_id": ""}
        decision = self.decide(task)
        return {"decision": decision.to_dict(), "explanation": self.explain(decision, task)}

    def list_policy_suggestions(self, project_id: str) -> dict[str, Any]:
        suggestions = PolicyUpdateEngine(self.db).generate_suggestions(project_id)
        return {"suggestions": suggestions, "count": len(suggestions)}

    def approve_policy_suggestion(self, suggestion_id: int, user: str = "codex") -> dict[str, Any]:
        return PolicyUpdateEngine(self.db).approve_suggestion(suggestion_id, user=user)

    def reject_policy_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        return PolicyUpdateEngine(self.db).reject_suggestion(suggestion_id)

    def record_user_decision(self, task: dict[str, Any], decision: str, feedback: str = "") -> None:
        ApprovalMemory(self.db).record_outcome(
            task_id=task["task_id"],
            project_id=task.get("project_id", ""),
            task_type=task.get("task_type", self.classify_task_type(task.get("user_goal", ""), {})),
            risk_level=task.get("risk_level", "medium"),
            approval_mode="HARD_APPROVAL",
            user_decision=decision,
            user_feedback=feedback,
        )
