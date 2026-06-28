"""Router V2: FeatureExtractor → Classifier → SafetyGate → Candidates → Scorer → Conflict → Policy → Decision.

Backward compatible with V1 plan_route(task, project, history) interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .routing.features import extract_features
from .routing.classifier import classify_task
from .routing.safety import safety_gate
from .routing.candidates import build_candidates
from .routing.scorer import score_candidates
from .routing.conflict import resolve_conflicts
from .routing.policy import apply_policy_overrides, build_retry_chain
from .routing.decision import make_decision
from .routing.schema import RouteV2
from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier


@dataclass
class Route:
    """Route decision. V2 adds intensity/confidence/task_labels/matched_rules/rejected_candidates."""
    selected_model: str
    selected_worker: str
    reason: str
    fallback_models: list[str] = field(default_factory=list)
    max_retries: int = 2
    escalation_policy: str = "codex_review_or_needs_user"
    variant: str | None = None
    # V2 fields
    intensity: str = "medium"
    capability_tier: str = "default"
    capability_profile: dict[str, Any] | None = None
    confidence: float = 0.5
    task_labels: dict[str, Any] | None = None
    matched_rules: list[str] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    retry_chain: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    requires_hard_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "selected_model": self.selected_model,
            "selected_worker": self.selected_worker,
            "selected_llm": self.selected_model,
            "selected_agent": self.selected_worker,
            "agent_llm": agent_llm_name(self.selected_worker, self.selected_model),
            "reason": self.reason,
            "fallback_models": self.fallback_models,
            "max_retries": self.max_retries,
            "escalation_policy": self.escalation_policy,
            "variant": self.variant,
            "intensity": self.intensity,
            "capability_tier": self.capability_tier,
            "capability_profile": self.capability_profile
            or capability_profile(self.selected_model, self.capability_tier, self.intensity),
            "confidence": self.confidence,
        }
        if self.task_labels:
            d["task_labels"] = self.task_labels
        if self.matched_rules:
            d["matched_rules"] = self.matched_rules
        if self.rejected_candidates:
            d["rejected_candidates"] = self.rejected_candidates
        if self.retry_chain:
            d["retry_chain"] = self.retry_chain
        if self.blocked:
            d["blocked"] = True
        if self.requires_hard_approval:
            d["requires_hard_approval"] = True
        return d


def plan_route(
    task: dict[str, Any],
    project: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> Route:
    """Route a task to the correct worker+model pair.

    Hotpatch rules (priority over older designs):
    - ClaudeCodeWorker only: DeepSeek / MiMo (never GLM)
    - GLM-5.2 only via OpenCodeWorker + opencode-go/glm-5.2
    - Default worker: ClaudeCodeWorker + deepseek_pro
    - Hermes: removed, not routed
    """
    project = project or {}
    task_type = str(task.get("task_type", ""))
    risk_level = str(task.get("risk_level", "medium"))

    # ── Phase 1: Feature Extraction ──
    features = extract_features(task, project)

    # ── Phase 2: Task Classification ──
    labels = classify_task(features)

    # ── Phase 3: Safety Gate ──
    safety = safety_gate(task, project, features, labels)

    if safety.blocked:
        return Route(
            selected_model="",
            selected_worker="",
            reason=f"BLOCKED: {safety.reason}",
            fallback_models=[],
            max_retries=0,
            blocked=True,
            intensity="",
            confidence=1.0,
        )

    # ── Phase 4: Candidate Building ──
    candidates = build_candidates(task, project, features, labels)

    # ── Phase 5: Candidate Scoring ──
    scored = score_candidates(candidates, task, project, features, labels, history)

    # ── Phase 6: Conflict Resolution ──
    resolved = resolve_conflicts(scored, features, labels)

    # ── Phase 7: Policy Override ──
    resolved = apply_policy_overrides(resolved, task, project, history)

    # ── Build retry chain ──
    retry_chain = build_retry_chain(resolved, task, project)

    # ── Phase 8: Final Decision ──
    matched_rules = resolved.reasons.copy()

    # ── Project stack matching ──
    stack = {str(x).lower() for x in project.get("stack", [])}
    if {"android", "kotlin", "fastapi", "react", "vue"} & stack:
        default_worker = project.get("default_worker")
        default_model = project.get("default_model")
        # Sanitize: GLM model with claude_code worker → override to deepseek_pro
        if default_worker == "claude_code" and default_model and _is_glm_model(default_model):
            default_model = "deepseek_pro"
        if default_worker == "opencode":
            resolved.worker = "opencode"
            resolved.model = default_model or "opencode-go/glm-5.2"
            resolved.reasons.append(f"project stack match ({stack}), worker={resolved.worker}")
            # ── A2: project.default_variant as fallback when V2 pipeline set no variant ──
            # Strong route variants (explicit_glm52/complex/hard_bugfix) are already set
            # by the candidate builder and preserved here. Only when resolved.variant is
            # None (普通 opencode fallback) do we consult project.default_variant.
            # "default" maps to None (= omit --variant, save quota).
            if resolved.variant is None:
                resolved.variant = _normalize_project_variant(project.get("default_variant"))
                if resolved.variant is not None:
                    resolved.reasons.append(
                        f"variant from project.default_variant={project.get('default_variant')!r}"
                    )
        elif (
            default_worker == "claude_code"
            and resolved.worker == "claude_code"
            and default_model
            and _is_deepseek_model(resolved.model)
        ):
            resolved.model = default_model
            resolved.reasons.append(f"project stack match, model={resolved.model}")
        elif default_model and not default_worker and resolved.worker == "claude_code" and _is_deepseek_model(resolved.model):
            resolved.model = default_model
        matched_rules = resolved.reasons.copy()

    decision = make_decision(
        resolved, labels, scored,
        matched_rules=matched_rules,
        retry_chain=retry_chain,
        blocked=False,
        requires_hard_approval=safety.requires_hard_approval,
    )

    # ── Enforce hard rules ──
    return _apply_capability_profile(_enforce_hard_rules(decision, task_type, risk_level, project))


def _enforce_hard_rules(decision: RouteV2, task_type: str, risk_level: str, project: dict[str, Any] | None = None) -> Route:
    """Enforce hard routing rules that must never be violated.

    1. ClaudeCodeWorker never gets GLM
    2. GLM-5.2 only through OpenCodeWorker
    3. Complex task types go to OpenCode
    """
    worker = decision.selected_worker
    model = decision.selected_model

    # Rule: GLM model must go through OpenCodeWorker OR be sanitized for ClaudeCodeWorker
    if _is_glm_model(model) and worker != "opencode":
        # If ClaudeCodeWorker, sanitize model to deepseek_pro
        if worker == "claude_code":
            model = "deepseek_pro"
            decision.selected_model = "deepseek_pro"
            decision.matched_rules.append("claude_code_glm_sanitized_to_deepseek")
        else:
            # Other workers: route through OpenCode
            worker = "opencode"
            decision.selected_worker = "opencode"
            decision.matched_rules.append("glm_model_sanitized_to_opencode")

    # Explicit complex_coding / hard_bugfix task_type → OpenCode
    # large_refactor / large_context → ClaudeCodeWorker with escalation (V2 policy)
    _direct_opencode_types = {"complex_coding", "hard_bugfix"}
    if task_type in _direct_opencode_types and worker != "opencode":
        variant = "max" if task_type == "hard_bugfix" else "high"
        decision.selected_worker = "opencode"
        decision.selected_model = "opencode-go/glm-5.2"
        decision.variant = variant
        decision.intensity = "max" if task_type == "hard_bugfix" else "high"
        decision.matched_rules.append(f"explicit_{task_type}_overrides_to_opencode")

    return Route(
        selected_model=decision.selected_model,
        selected_worker=decision.selected_worker,
        reason="; ".join(decision.matched_rules) if decision.matched_rules else decision.reason,
        fallback_models=decision.fallback_models,
        max_retries=decision.max_retries,
        escalation_policy=decision.escalation_policy,
        variant=decision.variant,
        intensity=decision.intensity,
        capability_tier=normalize_capability_tier(None, decision.intensity),
        capability_profile=capability_profile(
            decision.selected_model,
            normalize_capability_tier(None, decision.intensity),
            decision.intensity,
        ),
        confidence=decision.confidence,
        task_labels=decision.task_labels.to_dict() if decision.task_labels else None,
        matched_rules=decision.matched_rules,
        rejected_candidates=decision.rejected_candidates,
        retry_chain=decision.retry_chain,
        blocked=decision.blocked,
        requires_hard_approval=decision.requires_hard_approval,
    )


def _apply_capability_profile(route: Route) -> Route:
    tier_hint = route.variant if route.selected_worker == "opencode" and route.variant in {"high", "max"} else route.capability_tier
    route.capability_tier = normalize_capability_tier(tier_hint, route.intensity)
    route.capability_profile = capability_profile(route.selected_model, route.capability_tier, route.intensity)
    if route.selected_worker == "opencode":
        route.variant = route.capability_profile.get("variant")
    return route


def _is_glm_model(model: str) -> bool:
    """Check if a model name refers to GLM (which must only go through OpenCode)."""
    glm_patterns = ["glm", "z_ai", "z.ai", "chatglm"]
    return any(p in model.lower() for p in glm_patterns)


def _is_deepseek_model(model: str) -> bool:
    return "deepseek" in model.lower()


# opencode CLI only accepts high | max | minimal. "default" / None / unknown → omit flag.
_OPENCODE_CLI_VARIANTS = {"high", "max", "minimal"}


def _normalize_project_variant(value: str | None) -> str | None:
    """Normalize project.default_variant to a CLI-acceptable variant or None.

    - None / "" / "default" → None (= omit --variant, save quota)
    - high / max / minimal → passthrough
    - unknown → None (never pass an illegal value to the CLI)
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    if v == "" or v == "default":
        return None
    if v in _OPENCODE_CLI_VARIANTS:
        return v
    return None
