import pytest

from orchestrator.state_machine import (
    InvalidTransitionError, TaskState,
    apply_event, can_transition, resolve_state, resolve_state_old,
    STATE_ALIASES,
)


def test_valid_transition():
    assert can_transition("QUEUED", "PROJECT_DETECTED")
    state = apply_event(TaskState("t1", "QUEUED"), "PROJECT_DETECTED")
    assert state.status == "PROJECT_DETECTED"


def test_invalid_transition():
    with pytest.raises(InvalidTransitionError):
        apply_event(TaskState("t1", "QUEUED"), "COMPLETED")


# ── New tests ──

def test_old_state_aliases_resolve():
    """Old state names should resolve to new canonical names."""
    assert resolve_state("QUEUED") == "NEW"
    assert resolve_state("PROJECT_DETECTED") == "CLASSIFIED"
    assert resolve_state("RUNNING") == "EXECUTING"
    assert resolve_state("REVIEWING") == "CODEX_REVIEWING"
    assert resolve_state("COMPLETED") == "DONE"
    assert resolve_state("COMPLETED_NO_CHANGES") == "DONE"
    assert resolve_state("DRY_RUN_COMPLETED") == "DONE"


def test_new_states_remain_unchanged():
    """New state names should pass through resolve_state unchanged."""
    assert resolve_state("NEW") == "NEW"
    assert resolve_state("BLOCKED") == "BLOCKED"
    assert resolve_state("POLICY_LEARNING") == "POLICY_LEARNING"
    assert resolve_state("DONE") == "DONE"


def test_reverse_state_alias():
    """New states should resolve back to old names for DB compat."""
    assert resolve_state_old("NEW") == "QUEUED"
    assert resolve_state_old("EXECUTING") == "RUNNING"
    assert resolve_state_old("CODEX_REVIEWING") == "REVIEWING"


def test_new_approval_flow_transitions():
    """Full new approval flow transitions should be valid."""
    flow = [
        "NEW", "CLASSIFIED", "DYNAMIC_RISK_SCORED", "APPROVAL_DECIDED",
        "AUTO_SILENT", "PLANNED", "ROUTED", "WORKTREE_CREATED",
        "EXECUTING", "VERIFYING", "CODEX_REVIEWING",
        "POLICY_LEARNING", "PR_CREATED", "DONE",
    ]
    for i in range(len(flow) - 1):
        assert can_transition(flow[i], flow[i + 1]), f"transition {flow[i]} -> {flow[i + 1]} should be valid"


def test_blocked_state():
    """BLOCKED state should allow transition to NEEDS_USER or CANCELLED."""
    assert can_transition("BLOCKED", "NEEDS_USER")
    assert can_transition("BLOCKED", "CANCELLED")


def test_terminal_states():
    """Terminal states should have no outgoing transitions."""
    for state in ["DONE", "DONE_WITH_BLOCK", "COMPLETED_NO_CHANGES", "DRY_RUN_COMPLETED", "FAILED_FINAL", "CANCELLED", "ROLLED_BACK"]:
        assert can_transition(state, "NEW") is False
        assert can_transition(state, "DONE") is False


def test_retry_flow():
    """FAILED state should allow retry escalation."""
    assert can_transition("FAILED", "RETRYING")
    assert can_transition("RETRYING", "EXECUTING")
    assert can_transition("FAILED", "ESCALATED")
