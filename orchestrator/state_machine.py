from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


class InvalidTransitionError(ValueError):
    pass


# ── Old-to-new state name aliases (backward compatibility) ──
STATE_ALIASES: dict[str, str] = {
    "QUEUED": "NEW",
    "PROJECT_DETECTED": "CLASSIFIED",
    "WORKTREE_READY": "WORKTREE_CREATED",
    "RUNNING": "EXECUTING",
    "REVIEWING": "CODEX_REVIEWING",
    "READY_TO_PUBLISH": "PLANNED",
    "COMPLETED": "DONE",
    "COMPLETED_WITH_PATCH": "DONE_WITH_BLOCK",
    "COMPLETED_NO_CHANGES": "DONE",
    "COMPLETED_WITH_ARTIFACTS": "DONE",
    "DRY_RUN_COMPLETED": "DONE",
}

# ── Reverse map: new → list of old names ──
STATE_REVERSE_ALIASES: dict[str, list[str]] = {}
for _old, _new in STATE_ALIASES.items():
    STATE_REVERSE_ALIASES.setdefault(_new, []).append(_old)


def resolve_state(state_name: str) -> str:
    """Resolve a state name (old or new) to its canonical new name."""
    return STATE_ALIASES.get(state_name, state_name)


def resolve_state_old(state_name: str) -> str:
    """Resolve a new state name back to old name if available (for DB compat)."""
    for old, new in STATE_ALIASES.items():
        if new == state_name:
            return old
    return state_name


# ── Transition table using canonical new state names ──
#
# Full lifecycle:
#   NEW → CLASSIFIED → DYNAMIC_RISK_SCORED → APPROVAL_DECIDED
#     → AUTO_SILENT | AUTO_WITH_SUMMARY | SOFT_APPROVAL_WAITING | HARD_APPROVAL_WAITING | BLOCKED
#     → PLANNED → ROUTED → WORKTREE_CREATED → EXECUTING
#     → VERIFYING → CODEX_REVIEWING → POLICY_LEARNING → PR_CREATED → DONE
#
# Terminal: DONE, DONE_WITH_BLOCK, FAILED, FAILED_FINAL, CANCELLED, ROLLED_BACK

TRANSITIONS: dict[str, set[str]] = {
    # ── Pre-execution approval flow ──
    "NEW": {"CLASSIFIED", "NEEDS_USER"},
    "CLASSIFIED": {"DYNAMIC_RISK_SCORED", "NEEDS_USER"},
    "DYNAMIC_RISK_SCORED": {"APPROVAL_DECIDED"},
    "APPROVAL_DECIDED": {
        "AUTO_SILENT", "AUTO_WITH_SUMMARY",
        "SOFT_APPROVAL_WAITING", "HARD_APPROVAL_WAITING",
        "BLOCKED",
    },
    "AUTO_SILENT": {"PLANNED"},
    "AUTO_WITH_SUMMARY": {"PLANNED"},
    "SOFT_APPROVAL_WAITING": {"PLANNED", "CANCELLED"},
    "HARD_APPROVAL_WAITING": {"PLANNED", "CANCELLED", "NEEDS_USER"},
    "BLOCKED": {"NEEDS_USER", "CANCELLED"},

    # ── Execution flow ──
    "PLANNED": {"ROUTED"},
    "ROUTED": {"WORKTREE_CREATED", "ESCALATED"},
    "WORKTREE_CREATED": {"EXECUTING", "FAILED_FINAL"},
    "EXECUTING": {"VERIFYING", "RETRYING", "FAILED", "FAILED_FINAL", "CANCELLED"},
    "RETRYING": {"EXECUTING", "ESCALATED"},
    "VERIFYING": {"CODEX_REVIEWING", "FAILED", "FAILED_FINAL"},
    "CODEX_REVIEWING": {"POLICY_LEARNING", "NEEDS_USER", "NEEDS_REVIEW", "FAILED_FINAL"},

    # ── Post-execution flow ──
    "POLICY_LEARNING": {"PR_CREATED", "DONE", "DONE_WITH_BLOCK"},
    "PR_CREATED": {"DONE"},

    # ── Recovery / escalation ──
    "NEEDS_USER": {"NEW", "CANCELLED"},
    "NEEDS_REVIEW": {"PLANNED", "CANCELLED"},
    "ESCALATED": {"NEEDS_USER", "FAILED_FINAL"},
    "FAILED": {"RETRYING", "ESCALATED", "FAILED_FINAL", "NEEDS_USER"},

    # ── Terminal states ──
    "DONE": frozenset(),
    "DONE_WITH_BLOCK": frozenset(),
    "FAILED_FINAL": frozenset(),
    "CANCELLED": frozenset(),
    "ROLLED_BACK": frozenset(),
}


# ── Build old-name transition table for backward compat ──
def _build_old_transitions() -> dict[str, set[str]]:
    """Build transition table using old state names for backward compat."""
    old_map: dict[str, set[str]] = {}
    for from_state, to_states in TRANSITIONS.items():
        from_old = resolve_state_old(from_state)
        old_map.setdefault(from_old, set())
        for ts in to_states:
            old_map[from_old].add(resolve_state_old(ts))
    # Add old-only states
    old_map.setdefault("PUBLISHING", {"PR_CREATED", "COMPLETED_WITH_PATCH", "FAILED_FINAL"})
    old_map.setdefault("COMPLETED", set())
    old_map.setdefault("COMPLETED_WITH_PATCH", set())
    old_map.setdefault("COMPLETED_NO_CHANGES", set())
    old_map.setdefault("COMPLETED_WITH_ARTIFACTS", set())
    old_map.setdefault("DRY_RUN_COMPLETED", set())
    return old_map


OLD_TRANSITIONS: dict[str, set[str]] = _build_old_transitions()

# Merge old transitions for backward compatibility
_TRANSITIONS_MERGED: dict[str, set[str]] = {}
_TRANSITIONS_MERGED.update(OLD_TRANSITIONS)
_TRANSITIONS_MERGED.update(TRANSITIONS)

# Include old terminal states
_TRANSITIONS_MERGED["COMPLETED"] = frozenset()
_TRANSITIONS_MERGED["COMPLETED_WITH_PATCH"] = frozenset()
_TRANSITIONS_MERGED["COMPLETED_NO_CHANGES"] = frozenset()
_TRANSITIONS_MERGED["COMPLETED_WITH_ARTIFACTS"] = frozenset()
_TRANSITIONS_MERGED["DRY_RUN_COMPLETED"] = frozenset()
_TRANSITIONS_MERGED["PUBLISHING"] = {"PR_CREATED", "COMPLETED_WITH_PATCH", "FAILED_FINAL"}


@dataclass(frozen=True)
class TaskState:
    task_id: str
    status: str


def can_transition(from_state: str, to_state: str) -> bool:
    # Resolve old → new, check both
    from_new = resolve_state(from_state)
    to_new = resolve_state(to_state)
    allowed = _TRANSITIONS_MERGED.get(from_new, set()) | _TRANSITIONS_MERGED.get(from_state, set())
    return to_new in allowed or to_state in allowed


def apply_event(current: TaskState, to_state: str) -> TaskState:
    if not can_transition(current.status, to_state):
        raise InvalidTransitionError(f"illegal transition: {current.status} -> {to_state}")
    return TaskState(task_id=current.task_id, status=to_state)
