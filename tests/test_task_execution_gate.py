import json
from pathlib import Path

from orchestrator.approval_policy_service import ApprovalPolicyService
from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB
from orchestrator.task_execution_gate import TaskExecutionGate


def _gate(tmp_path: Path) -> tuple[TaskExecutionGate, ArtifactStore]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    return TaskExecutionGate(
        artifacts=artifacts,
        approval_policy=ApprovalPolicyService(db),
    ), artifacts


def _task(goal: str, risk_level: str = "low") -> dict:
    return {
        "task_id": "t_gate",
        "project_id": "proj",
        "user_goal": goal,
        "risk_level": risk_level,
        "auto_pr": False,
        "auto_merge": False,
    }


def test_execution_gate_blocks_static_risk_and_marks_policy_incident(tmp_path: Path):
    gate, artifacts = _gate(tmp_path)
    task = _task("run rm -rf / on this machine", risk_level="high")

    result = gate.run(task, {"repo": str(tmp_path)})

    assert result.continue_execution is False
    assert result.policy_incident is True
    assert result.transitions[0].status == "FAILED_FINAL"
    assert result.transitions[0].event_type == "risk_blocked"
    risk = json.loads(artifacts.path("t_gate", "risk.json").read_text(encoding="utf-8"))
    assert risk["allowed"] is False


def test_execution_gate_hard_approval_writes_explanation(tmp_path: Path):
    gate, artifacts = _gate(tmp_path)
    task = _task("edit deploy/prod/release.yaml", risk_level="medium")
    task["planned_files"] = ["deploy/prod/release.yaml"]

    result = gate.run(task, {"repo": str(tmp_path)})

    assert result.continue_execution is False
    assert result.policy_incident is False
    assert [transition.status for transition in result.transitions][-1] == "HARD_APPROVAL_WAITING"
    approval = json.loads(artifacts.path("t_gate", "approval.json").read_text(encoding="utf-8"))
    assert approval["mode"] == "HARD_APPROVAL"
    explanation = artifacts.path("t_gate", "approval_explanation.md").read_text(encoding="utf-8")
    assert "Approval Decision" in explanation


def test_execution_gate_low_risk_continues_after_auto_summary(tmp_path: Path):
    gate, artifacts = _gate(tmp_path)
    task = _task("update README typo", risk_level="low")

    result = gate.run(task, {"repo": str(tmp_path)})

    assert result.continue_execution is True
    assert task["task_type"]
    assert [transition.status for transition in result.transitions] == [
        "CLASSIFIED",
        "DYNAMIC_RISK_SCORED",
        "APPROVAL_DECIDED",
        "AUTO_WITH_SUMMARY",
    ]
    approval = json.loads(artifacts.path("t_gate", "approval.json").read_text(encoding="utf-8"))
    assert approval["mode"] == "AUTO_WITH_SUMMARY"


def test_execution_gate_skips_second_approval_after_user_approval(tmp_path: Path):
    gate, artifacts = _gate(tmp_path)
    task = _task("edit deploy/prod/release.yaml", risk_level="medium")
    task["planned_files"] = ["deploy/prod/release.yaml"]
    task["_approval_granted"] = True

    result = gate.run(task, {"repo": str(tmp_path)})

    assert result.continue_execution is True
    assert result.transitions == []
    assert task["task_type"]
    assert not artifacts.path("t_gate", "approval.json").exists()
