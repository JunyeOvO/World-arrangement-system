"""Tests for dynamic approval trust scoring and learning."""
import tempfile
from pathlib import Path

from orchestrator.db import TaskDB
from orchestrator.approval_memory import ApprovalMemory
from orchestrator.policy_update_engine import PolicyUpdateEngine


def _make_db():
    p = Path(tempfile.mkdtemp()) / "test.db"
    return TaskDB(p)


def test_rollback_demotes_trust():
    """Hotpatch: rollback should decrease trust score."""
    db = _make_db()
    engine = PolicyUpdateEngine(db)

    # Build trust with successes
    for _ in range(5):
        engine.on_task_complete(
            "t_test", "proj", "simple_bugfix", "low", "AUTO_SILENT",
            "claude_code", "deepseek_pro", None, 2, 2, ["src/**"],
            True, True, True, rollback=False, incident=False,
        )
    pats = db.get_learned_patterns("proj", active_only=True)
    assert len(pats) > 0
    initial_trust = pats[0]["trust_score"]

    # Simulate rollback
    engine.on_task_complete(
        "t_rollback", "proj", "simple_bugfix", "low", "AUTO_SILENT",
        "claude_code", "deepseek_pro", None, 2, 2, ["src/**"],
        False, False, False, rollback=True, incident=False,
    )
    pats2 = db.get_learned_patterns("proj", active_only=True)
    after_trust = pats2[0]["trust_score"] if pats2 else 0.5
    assert after_trust < initial_trust or after_trust <= 0.7, \
        f"Trust should decrease after rollback: {initial_trust} -> {after_trust}"


def test_repeated_low_risk_can_auto():
    """Hotpatch: repeated low-risk success should allow auto approval."""
    db = _make_db()
    mem = ApprovalMemory(db)

    # Simulate 10 successful low-risk simple_bugfix tasks
    for i in range(10):
        mem.learn_from_outcome(
            "proj", "simple_bugfix", "src/**", success=True, rollback=False,
            worker="claude_code", model="deepseek_pro",
        )
    pats = db.get_learned_patterns("proj", active_only=True)
    assert len(pats) > 0
    trust = pats[0]["trust_score"]
    assert trust > 0.5, f"Trust should grow after repeated success: {trust}"
    # Suggested mode should allow auto
    suggested = pats[0].get("suggested_mode", "")
    assert "AUTO" in suggested, f"Expected AUTO suggestion for trusted low-risk pattern, got {suggested}"


def test_high_risk_never_auto():
    """Hotpatch: high risk task should never get AUTO_SILENT even with history."""
    from orchestrator.approval_graph import ApprovalGraph, ApprovalMode

    db = _make_db()
    mem = ApprovalMemory(db)

    # Build trust for a pattern
    for _ in range(10):
        mem.learn_from_outcome(
            "proj", "routine_coding", "src/**", success=True,
            worker="claude_code", model="deepseek_pro",
        )

    # High risk task checking — even with good history, should be HARD approval
    graph = ApprovalGraph(db)
    decision = graph.decide({
        "user_goal": "refactor auth middleware internals",
        "risk_level": "high", "project_id": "proj", "task_type": "complex_coding",
    })
    assert decision.mode != ApprovalMode.AUTO_SILENT, \
        f"high risk should never be AUTO_SILENT, got {decision.mode}"
    assert decision.mode != ApprovalMode.AUTO_WITH_SUMMARY, \
        f"high risk should never be AUTO_WITH_SUMMARY, got {decision.mode}"
