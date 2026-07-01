"""Risk and approval gate for task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .approval_graph import ApprovalMode
from .approval_policy_service import ApprovalPolicyService
from .artifacts import ArtifactStore
from .risk_policy import evaluate_task


@dataclass
class StatusTransition:
    status: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class ExecutionGateResult:
    continue_execution: bool
    task_type: str
    transitions: list[StatusTransition] = field(default_factory=list)
    policy_incident: bool = False


class TaskExecutionGate:
    """Owns pre-route task classification, static risk, and approval decisions."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        approval_policy: ApprovalPolicyService,
        risk_evaluator: Callable[..., Any] = evaluate_task,
    ) -> None:
        self.artifacts = artifacts
        self.approval_policy = approval_policy
        self.risk_evaluator = risk_evaluator

    def run(self, task: dict[str, Any], project: dict[str, Any]) -> ExecutionGateResult:
        task_id = task["task_id"]
        task_type = self.approval_policy.classify_task_type(task["user_goal"], project)
        task["task_type"] = task_type
        if task.get("_approval_granted"):
            return ExecutionGateResult(
                continue_execution=True,
                task_type=task_type,
                transitions=[],
            )

        risk = self.risk_evaluator(
            task["user_goal"],
            task["risk_level"],
            task["auto_pr"],
            task["auto_merge"],
        )
        self.artifacts.write_json(task_id, "risk.json", risk.__dict__)
        if not risk.allowed:
            return ExecutionGateResult(
                continue_execution=False,
                task_type=task_type,
                transitions=[
                    StatusTransition("FAILED_FINAL", "risk_blocked", risk.__dict__),
                ],
                policy_incident=True,
            )

        approval = self.approval_policy.decide(task, project)
        approval_payload = approval.to_dict()
        self.artifacts.write_json(task_id, "approval.json", approval_payload)
        transitions = [
            StatusTransition("CLASSIFIED", "classified", {"task_type": task_type}),
        ]

        if approval.mode == ApprovalMode.BLOCKED:
            transitions.append(StatusTransition("BLOCKED", "approval_blocked", approval_payload))
            return ExecutionGateResult(False, task_type, transitions)

        transitions.extend([
            StatusTransition("DYNAMIC_RISK_SCORED", "risk_scored", {"risk_score": approval.risk_score}),
            StatusTransition("APPROVAL_DECIDED", "approval_decided", approval_payload),
        ])

        if approval.mode == ApprovalMode.HARD_APPROVAL:
            transitions.append(StatusTransition("HARD_APPROVAL_WAITING", "awaiting_hard_approval", approval_payload))
            self.artifacts.write_text(
                task_id,
                "approval_explanation.md",
                self.approval_policy.explain(approval, task),
            )
            return ExecutionGateResult(False, task_type, transitions)
        if approval.mode == ApprovalMode.SOFT_APPROVAL:
            transitions.append(StatusTransition("SOFT_APPROVAL_WAITING", "awaiting_soft_approval", approval_payload))
        elif approval.mode == ApprovalMode.AUTO_SILENT:
            transitions.append(StatusTransition("AUTO_SILENT", "auto_silent", approval_payload))
        elif approval.mode == ApprovalMode.AUTO_WITH_SUMMARY:
            transitions.append(StatusTransition("AUTO_WITH_SUMMARY", "auto_with_summary", approval_payload))

        return ExecutionGateResult(True, task_type, transitions)
