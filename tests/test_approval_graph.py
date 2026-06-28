"""Tests for Dynamic Approval Graph (Phase 3 upgrade)."""
from orchestrator.approval_graph import (
    ApprovalGraph, ApprovalMode, ApprovalDecision,
    check_hard_risk, _classify_task_type,
)


def test_hard_risk_forbidden_paths_blocked():
    """Non-reversible commands (rm -rf /, git push --force) should still be blocked."""
    issues, warnings = check_hard_risk("run rm -rf / on the server")
    assert len(issues) > 0
    assert any("rm -rf" in i for i in issues)


def test_hard_risk_safe_task_passes():
    """Safe tasks should produce no blocking issues and no warnings."""
    issues, warnings = check_hard_risk("fix typo in README")
    assert len(issues) == 0
    assert len(warnings) == 0


def test_sensitive_topic_keywords_produce_warnings_only():
    """Sensitive topics (auth, payment, deploy) should produce WARNINGS, not blocking issues."""
    issues, warnings = check_hard_risk("deploy to production and update database migration")
    assert len(issues) == 0, f"Expected no blocking issues, got: {issues}"
    assert len(warnings) > 0, "Expected warnings for sensitive topics"


def test_non_reversible_command_blocked():
    """git push --force should be BLOCKED."""
    graph = ApprovalGraph()
    decision = graph.decide({
        "user_goal": "git push --force to origin",
        "risk_level": "medium",
        "project_id": "generic",
    })
    assert decision.mode == ApprovalMode.BLOCKED
    assert len(decision.blocking_issues) > 0


def test_approval_graph_low_risk_auto():
    """Low risk tasks should get AUTO_WITH_SUMMARY."""
    graph = ApprovalGraph()
    decision = graph.decide({
        "user_goal": "fix typo in readme",
        "risk_level": "low",
        "project_id": "generic",
    })
    assert decision.mode in (ApprovalMode.AUTO_SILENT, ApprovalMode.AUTO_WITH_SUMMARY)


def test_approval_graph_high_risk_soft_approval():
    """High risk tasks WITHOUT real danger should get SOFT_APPROVAL (Phase 3 change)."""
    graph = ApprovalGraph()
    decision = graph.decide({
        "user_goal": "refactor the entire routing layer",
        "risk_level": "high",
        "project_id": "generic",
    })
    assert decision.mode == ApprovalMode.SOFT_APPROVAL, \
        f"Expected SOFT_APPROVAL for high risk without real danger, got {decision.mode}"
    assert decision.requires_plan


def test_approval_graph_keywords_no_longer_blocked():
    """Sensitive keywords (deploy/production/migration) should NOT block — WARN only."""
    graph = ApprovalGraph()
    decision = graph.decide({
        "user_goal": "deploy to production and update database migration",
        "risk_level": "high",
        "project_id": "generic",
    })
    # Keywords like deploy/production/migration are now WARN only
    assert decision.mode != ApprovalMode.BLOCKED, \
        f"Sensitive keywords should not BLOCK, got {decision.mode}"
    assert decision.mode == ApprovalMode.SOFT_APPROVAL
    # Should still have warnings about sensitive topics
    assert len(decision.warnings) > 0


def test_approval_decision_to_dict():
    """ApprovalDecision.to_dict() should return serializable result."""
    decision = ApprovalDecision(ApprovalMode.SOFT_APPROVAL, "test", 0.5)
    d = decision.to_dict()
    assert d["mode"] == "SOFT_APPROVAL"
    assert d["risk_score"] == 0.5
    assert d["reason"] == "test"


def test_classify_task_type():
    """Task type classification should categorize goals correctly."""
    assert _classify_task_type("update README with new instructions", {}) == "docs"
    assert _classify_task_type("add unit tests for user module", {}) == "test_generation"
    assert _classify_task_type("fix a simple typo bug", {}) == "simple_bugfix"
    assert _classify_task_type("fix a complex race condition crash", {}) == "hard_bugfix"
    assert _classify_task_type("refactor the entire auth system", {}) == "large_refactor"
    assert _classify_task_type("design new architecture for payments", {}) == "complex_coding"


def test_explain_decision_output():
    """explain_decision should return human-readable text."""
    from orchestrator.approval_explainer import explain_decision
    decision = ApprovalDecision(
        ApprovalMode.HARD_APPROVAL, "test reason", 0.8,
        blocking_issues=[], warnings=["test warning"],
        requires_plan=True,
    )
    explanation = explain_decision(decision, {"user_goal": "test goal", "project_id": "test"})
    assert "HARD_APPROVAL" in explanation
    assert "test reason" in explanation
    assert "test warning" in explanation
    assert "Plan Required" in explanation
