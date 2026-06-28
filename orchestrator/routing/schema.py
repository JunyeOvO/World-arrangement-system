"""Router V2 schema definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agent_llm import agent_llm_name
from ..llm_capability import capability_profile, normalize_capability_tier


@dataclass
class TaskFeatures:
    """Extracted features from a task."""
    goal_lower: str = ""
    keywords: list[str] = field(default_factory=list)
    target_paths: list[str] = field(default_factory=list)
    path_kinds: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    explicit_model_request: str | None = None
    requires_multimodal: bool = False
    risk_signals: list[str] = field(default_factory=list)
    blocked_signals: list[str] = field(default_factory=list)
    task_type: str = ""
    risk_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_lower": self.goal_lower,
            "keywords": self.keywords,
            "target_paths": self.target_paths,
            "path_kinds": self.path_kinds,
            "actions": self.actions,
            "objects": self.objects,
            "explicit_model_request": self.explicit_model_request,
            "requires_multimodal": self.requires_multimodal,
            "risk_signals": self.risk_signals,
            "blocked_signals": self.blocked_signals,
        }


@dataclass
class TaskLabels:
    """Classified task labels."""
    action: list[str] = field(default_factory=list)
    object: list[str] = field(default_factory=list)
    artifact_type: str = ""
    risk_domain: list[str] = field(default_factory=list)
    complexity: str = "low"
    requires_multimodal: bool = False
    explicit_model_request: str | None = None
    needs_code_change: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "object": self.object,
            "artifact_type": self.artifact_type,
            "risk_domain": self.risk_domain,
            "complexity": self.complexity,
            "requires_multimodal": self.requires_multimodal,
            "explicit_model_request": self.explicit_model_request,
            "needs_code_change": self.needs_code_change,
        }


@dataclass
class SafetyResult:
    """Safety gate result."""
    allowed: bool = True
    blocked: bool = False
    requires_hard_approval: bool = False
    reason: str = ""
    blocked_paths: list[str] = field(default_factory=list)

    def to_route_dict(self) -> dict[str, Any]:
        return {
            "selected_model": "",
            "selected_worker": "",
            "reason": f"BLOCKED: {self.reason}",
            "blocked": True,
        }


@dataclass
class CandidateRoute:
    """A candidate route with scoring."""
    worker: str
    model: str
    intensity: str = "medium"
    variant: str | None = None
    capability_tier: str = "default"
    capability_profile: dict[str, Any] | None = None
    base_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class RouteV2:
    """Full V2 route decision with explainability."""
    selected_worker: str
    selected_model: str
    intensity: str = "medium"
    variant: str | None = None
    reason: str = ""
    confidence: float = 0.5
    task_labels: TaskLabels = field(default_factory=TaskLabels)
    matched_rules: list[str] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    retry_chain: list[dict[str, Any]] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    max_retries: int = 2
    escalation_policy: str = "codex_review_or_needs_user"
    blocked: bool = False
    requires_hard_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_worker": self.selected_worker,
            "selected_model": self.selected_model,
            "selected_agent": self.selected_worker,
            "selected_llm": self.selected_model,
            "agent_llm": agent_llm_name(self.selected_worker, self.selected_model),
            "intensity": self.intensity,
            "variant": self.variant,
            "capability_tier": normalize_capability_tier(self.capability_tier, self.intensity),
            "capability_profile": self.capability_profile
            or capability_profile(
                self.selected_model,
                normalize_capability_tier(self.capability_tier, self.intensity),
                self.intensity,
            ),
            "reason": self.reason,
            "confidence": self.confidence,
            "task_labels": self.task_labels.to_dict(),
            "matched_rules": self.matched_rules,
            "rejected_candidates": self.rejected_candidates,
            "retry_chain": self.retry_chain,
            "fallback_models": self.fallback_models,
            "max_retries": self.max_retries,
            "escalation_policy": self.escalation_policy,
            "blocked": self.blocked,
            "requires_hard_approval": self.requires_hard_approval,
        }
