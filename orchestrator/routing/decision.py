"""RouteDecision: produce final RouteV2 from resolved candidate."""
from __future__ import annotations

from .schema import CandidateRoute, RouteV2, TaskLabels


def make_decision(
    resolved: CandidateRoute,
    labels: TaskLabels,
    all_candidates: list[CandidateRoute],
    matched_rules: list[str],
    retry_chain: list[dict[str, Any]],
    blocked: bool = False,
    requires_hard_approval: bool = False,
) -> RouteV2:
    """Build final RouteV2 decision from resolved candidate."""
    # Rejected candidates = all except resolved
    rejected = []
    for c in all_candidates:
        if c.worker != resolved.worker or c.model != resolved.model:
            rejected.append({
                "worker": c.worker,
                "model": c.model,
                "reason": "; ".join(c.reasons) if c.reasons else "scored lower",
                "score": c.score,
            })

    confidence = _calculate_confidence(resolved, matched_rules)

    return RouteV2(
        selected_worker=resolved.worker,
        selected_model=resolved.model,
        intensity=resolved.intensity,
        variant=resolved.variant,
        reason="; ".join(resolved.reasons) if resolved.reasons else "default route",
        confidence=confidence,
        task_labels=labels,
        matched_rules=matched_rules,
        rejected_candidates=rejected,
        retry_chain=retry_chain,
        fallback_models=_get_fallback_models(resolved),
        max_retries=1 if resolved.worker == "claude_code" else 2,
        escalation_policy=_get_escalation_policy(resolved),
        blocked=blocked,
        requires_hard_approval=requires_hard_approval,
    )


def _calculate_confidence(resolved: CandidateRoute, matched_rules: list[str]) -> float:
    """Calculate confidence score based on matched rules and score."""
    base = 0.5
    if resolved.score >= 100:
        base = 0.9
    elif resolved.score >= 70:
        base = 0.8
    elif resolved.score >= 50:
        base = 0.7
    elif resolved.score < 20:
        base = 0.4
    # Boost with matched rules
    base += min(len(matched_rules) * 0.03, 0.15)
    return min(base, 1.0)


def _get_fallback_models(resolved: CandidateRoute) -> list[str]:
    """Get fallback models based on selected route."""
    if resolved.worker == "claude_code":
        return ["opencode-go/glm-5.2", "deepseek_pro", "codex_reviewer"]
    elif resolved.worker == "opencode":
        return ["codex_reviewer"]
    return ["deepseek_pro", "codex_reviewer"]


def _get_escalation_policy(resolved: CandidateRoute) -> str:
    """Get escalation policy based on route."""
    if resolved.worker == "claude_code":
        return "opencode_on_failure"
    return "codex_review_or_needs_user"
