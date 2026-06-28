"""ConflictResolver: resolve conflicts between candidate routes."""
from __future__ import annotations

from typing import Any

from .schema import CandidateRoute, TaskFeatures, TaskLabels


def resolve_conflicts(
    scored: list[CandidateRoute],
    features: TaskFeatures,
    labels: TaskLabels,
) -> CandidateRoute:
    """Resolve conflicts and pick the best candidate route.

    Rules:
    1. Docs context (README/docs paths + docs actions) downgrades architecture/auth keywords
    2. auth/payment/database only high-risk when action is modify/refactor
    3. Multimodal tasks go to ClaudeCodeWorker with MiMo backend
    4. Explicit model requests have highest priority
    """
    if not scored:
        return CandidateRoute(worker="claude_code", model="deepseek_pro", intensity="medium")

    top = scored[0]

    # ── Rule 1: Docs context overrides architecture keyword ──
    is_docs_context = (
        labels.artifact_type == "docs"
        or "docs" in features.path_kinds
        or "docs" in features.actions
        or "readme" in features.goal_lower
    )
    has_architecture = "architecture" in features.objects
    has_risk_objects = bool({"auth", "database", "infra"} & set(features.objects))

    if is_docs_context and (has_architecture or has_risk_objects) and top.worker == "opencode":
        # Docs context: find best non-OpenCode candidate
        for c in scored:
            if c.worker != "opencode":
                if has_architecture:
                    c.reasons.append("architecture keyword in docs context -> treat as docs")
                if has_risk_objects and not labels.needs_code_change:
                    c.reasons.append("risk object in docs/analyze context -> not high-risk coding")
                return c

    # ── Rule 2: Explicit model request bypasses docs downgrade ──
    if features.explicit_model_request == "glm52":
        for c in scored:
            if c.worker == "opencode":
                c.reasons.insert(0, "explicit GLM-5.2 request (highest priority, safety gate passed)")
                return c

    # ── Rule 3: Multimodal always goes to ClaudeCodeWorker with MiMo backend ──
    if features.requires_multimodal:
        preferred_model = "mimo_v25_pro" if labels.needs_code_change else "mimo_v25"
        for c in scored:
            if c.worker == "claude_code" and c.model == preferred_model:
                return c
        for c in scored:
            if c.worker == "claude_code" and c.model in {"mimo_v25", "mimo_v25_pro"}:
                return c

    # ── Rule 4: Explicit complex_coding / hard_bugfix → OpenCode ──
    # These are explicit task_type signals (set by scheduler._classify_task_type or user)
    # Only complex_coding and hard_bugfix go directly to OpenCode.
    # large_refactor and large_context → ClaudeCodeWorker with escalation (Rule 5)
    if features.task_type == "hard_bugfix":
        for c in scored:
            if c.worker == "opencode" and c.intensity == "max":
                return c
    if features.task_type == "complex_coding":
        for c in scored:
            if c.worker == "opencode" and c.intensity == "high":
                c.reasons.append("explicit complex_coding -> GLM-5.2")
                return c

    # ── Rule 5: High risk objects/keywords → ClaudeCodeWorker with escalation ──
    # V2 philosophy: keyword-based classification routes to ClaudeCodeWorker first.
    # Only explicit user model request (Rule 2), hard_bugfix, or complex_coding go to OpenCode.
    # All other high-risk/complex tasks try ClaudeCodeWorker first, escalate to OpenCode on failure.
    if (has_risk_objects and labels.needs_code_change and not is_docs_context) or \
       (labels.complexity in ("high",)):
        for c in scored:
            if c.worker == "claude_code":
                if has_risk_objects:
                    c.reasons.insert(0, "high-risk object with code change -> ClaudeCodeWorker with escalation to OpenCode on failure")
                else:
                    c.reasons.insert(0, "high complexity keyword match → ClaudeCodeWorker with escalation")
                return c

    # ── Rule 6: README/docs always stays on ClaudeCode ──
    if is_docs_context:
        for c in scored:
            if c.worker == "claude_code":
                if "readme" in features.goal_lower:
                    c.reasons.insert(0, "README documentation task")
                else:
                    c.reasons.insert(0, "documentation task")
                return c

    return top
