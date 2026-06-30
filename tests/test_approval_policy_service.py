from orchestrator.approval_graph import ApprovalMode
from orchestrator.approval_memory import ApprovalMemory
from orchestrator.approval_policy_service import ApprovalPolicyService
from orchestrator.db import TaskDB


def _db(tmp_path):
    db = TaskDB(tmp_path / "state.db")
    db.init()
    return db


def test_decision_for_goal_wraps_decision_and_explanation(tmp_path):
    service = ApprovalPolicyService(_db(tmp_path))

    result = service.decision_for_goal("proj", "update README wording", risk_level="low")

    assert result["decision"]["mode"] == ApprovalMode.AUTO_WITH_SUMMARY.value
    assert "low risk" in result["decision"]["reason"]
    assert "Approval Decision" in result["explanation"]


def test_record_user_decision_persists_approval_event(tmp_path):
    db = _db(tmp_path)
    service = ApprovalPolicyService(db)
    task = {
        "task_id": "t_approval",
        "project_id": "proj",
        "user_goal": "refactor docs",
        "risk_level": "medium",
    }

    result = service.approve_task(task, user="tester")

    history = db.get_approval_history("proj")
    assert result == {"status": "approved", "task_id": "t_approval"}
    assert len(history) == 1
    assert history[0]["task_id"] == "t_approval"
    assert history[0]["user_decision"] == "approved"
    assert history[0]["approval_mode"] == "HARD_APPROVAL"
    assert history[0]["task_type"]


def test_reject_task_records_feedback_without_cancelling(tmp_path):
    db = _db(tmp_path)
    service = ApprovalPolicyService(db)
    task = {
        "task_id": "t_reject",
        "project_id": "proj",
        "user_goal": "touch deploy/prod config",
        "risk_level": "high",
    }

    result = service.reject_task(task, reason="needs manual rollout window")

    history = db.get_approval_history("proj")
    assert result == {"status": "rejected", "task_id": "t_reject"}
    assert history[0]["user_decision"] == "rejected"
    assert history[0]["user_feedback"] == "needs manual rollout window"


def test_learned_rules_listing_and_revocation(tmp_path):
    db = _db(tmp_path)
    service = ApprovalPolicyService(db)
    memory = ApprovalMemory(db)
    memory.learn_from_outcome(
        "proj",
        "simple_bugfix",
        "src/**",
        success=True,
        worker="claude_code",
        model="deepseek_pro",
    )
    pattern = db.get_learned_patterns("proj", active_only=True)[0]

    listed = service.list_learned_rules("proj")
    revoked = service.revoke_learned_rule(pattern["id"])

    assert len(listed["rules"]) == 1
    assert listed["summary"]
    assert revoked == {"status": "revoked", "pattern_id": pattern["id"]}
    assert db.get_learned_patterns("proj", active_only=True) == []
