import pytest

from orchestrator.db import TaskDB
from orchestrator.state_machine import (
    InvalidTransitionError, TaskState,
    apply_event, can_transition, resolve_state, resolve_state_old,
    STATE_ALIASES,
)
from orchestrator.task_lifecycle import TaskLifecycleController


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
    assert resolve_state("COMPLETED_WITH_ARTIFACTS") == "DONE"
    assert resolve_state("COMPLETED_WITH_PARTIAL_ARTIFACTS") == "DONE"
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


def test_review_unavailable_can_pause_for_human_review():
    assert can_transition("CODEX_REVIEWING", "NEEDS_REVIEW")
    assert can_transition("NEEDS_REVIEW", "PLANNED")
    assert can_transition("NEEDS_REVIEW", "CANCELLED")


def test_blocked_state():
    """BLOCKED state should allow transition to NEEDS_USER or CANCELLED."""
    assert can_transition("BLOCKED", "NEEDS_USER")
    assert can_transition("BLOCKED", "CANCELLED")


def test_terminal_states():
    """Terminal states should have no outgoing transitions."""
    for state in ["DONE", "DONE_WITH_BLOCK", "COMPLETED_NO_CHANGES", "COMPLETED_WITH_PARTIAL_ARTIFACTS", "DRY_RUN_COMPLETED", "FAILED_FINAL", "CANCELLED", "ROLLED_BACK"]:
        assert can_transition(state, "NEW") is False
        assert can_transition(state, "DONE") is False


def test_retry_flow():
    """FAILED state should allow retry escalation."""
    assert can_transition("FAILED", "RETRYING")
    assert can_transition("RETRYING", "EXECUTING")
    assert can_transition("FAILED", "ESCALATED")


def test_task_lifecycle_controller_updates_status_event_and_terminal_hook(tmp_path):
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": "t_lifecycle",
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "inspect project",
            "status": "EXECUTING",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(tmp_path / "run"),
        }
    )
    synced: list[str] = []
    outcomes: list[tuple[str, dict]] = []
    lifecycle = TaskLifecycleController(
        db,
        now=lambda: "2026-06-30T01:00:02Z",
        sync_task_artifact=synced.append,
        record_task_outcome=lambda task_id, metadata: outcomes.append((task_id, metadata)),
    )

    lifecycle.set_status("t_lifecycle", "COMPLETED_NO_CHANGES", "done", {"ok": True})

    task = db.get_task("t_lifecycle")
    events = db.list_events("t_lifecycle")
    assert task["status"] == "COMPLETED_NO_CHANGES"
    assert task["updated_at"] == "2026-06-30T01:00:02Z"
    assert synced == ["t_lifecycle"]
    assert events[-1]["event_type"] == "done"
    assert events[-1]["from_state"] == "EXECUTING"
    assert events[-1]["to_state"] == "COMPLETED_NO_CHANGES"
    assert outcomes == [("t_lifecycle", {"event_type": "done"})]
