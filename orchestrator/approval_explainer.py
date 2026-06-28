"""Approval Explainer — human-readable explanations of approval decisions.

Generates clear, structured explanations for:
- Why a task was blocked / auto-approved / needs approval
- What factors influenced the decision
- How to change the outcome (e.g., modify task, add policy override)
"""

from __future__ import annotations

from typing import Any

from .approval_graph import ApprovalDecision, ApprovalMode


def explain_decision(decision: ApprovalDecision, task: dict[str, Any] | None = None) -> str:
    """Generate a full human-readable explanation of an approval decision."""
    lines = [
        f"# Approval Decision: {decision.mode.value}",
        "",
        f"**Risk Score**: {decision.risk_score:.2f} / 1.0",
        f"**Reason**: {decision.reason}",
        "",
    ]

    if task:
        lines.append("## Task Context")
        lines.append(f"- Goal: {task.get('user_goal', 'N/A')[:120]}")
        lines.append(f"- Project: {task.get('project_id', 'N/A')}")
        lines.append(f"- Risk Level: {task.get('risk_level', 'N/A')}")
        lines.append(f"- Task Type: {task.get('task_type', 'N/A')}")
        lines.append("")

    if decision.blocking_issues:
        lines.append("## Blocking Issues (must be resolved)")
        for bi in decision.blocking_issues:
            lines.append(f"- 🚫 {bi}")
        lines.append("")

    if decision.warnings:
        lines.append("## Warnings")
        for w in decision.warnings:
            lines.append(f"- ⚠ {w}")
        lines.append("")

    if decision.matched_rule:
        lines.append(f"**Matched Rule**: `{decision.matched_rule}`")
        lines.append("")

    if decision.learned_pattern_id:
        lines.append(f"**Learned Pattern**: #{decision.learned_pattern_id}")
        lines.append("")

    if decision.requires_plan:
        lines.append("## ⚠ Plan Required")
        lines.append("This task requires a detailed execution plan before approval.")
        lines.append("")

    # ── Guidance ──
    lines.append("## What You Can Do")
    if decision.mode == ApprovalMode.BLOCKED:
        lines.append("- This task touches hard-risk boundaries and cannot be auto-executed.")
        lines.append("- Modify the task to avoid sensitive paths/operations.")
        lines.append("- If this is a false positive, add a project-level policy override.")
    elif decision.mode == ApprovalMode.HARD_APPROVAL:
        lines.append("- Review the execution plan carefully.")
        lines.append("- Approve explicitly if you agree with the scope.")
    elif decision.mode == ApprovalMode.SOFT_APPROVAL:
        lines.append("- Confirm the task in Codex to proceed.")
    elif decision.mode in (ApprovalMode.AUTO_SILENT, ApprovalMode.AUTO_WITH_SUMMARY):
        lines.append("- This task will execute automatically.")
        lines.append("- You can review the result in the summary.")

    return "\n".join(lines)


def explain_learned_rules(rules: list[dict[str, Any]]) -> str:
    """Generate a summary of learned rules."""
    if not rules:
        return "No learned rules for this project yet."

    lines = ["# Learned Approval Rules", ""]
    for i, r in enumerate(rules[:20], 1):
        lines.append(f"## Rule {i}: {r['task_type']} → {r.get('suggested_mode', 'N/A')}")
        lines.append(f"- Trust Score: {r['trust_score']:.2f}")
        lines.append(f"- Confidence: {r['confidence']:.2f}")
        lines.append(f"- Approvals: {r['approvals_count']} | Successes: {r['success_count']} | Failures: {r['failure_count']} | Rollbacks: {r['rollback_count']}")
        lines.append(f"- Path Pattern: {r['path_pattern']}")
        lines.append("")
    return "\n".join(lines)
