"""TaskClassifier: classify task features into structured labels."""
from __future__ import annotations

from .features import TaskFeatures
from .schema import TaskLabels

# ── Complexity mapping ──
_HIGH_COMPLEXITY_ACTIONS = {"refactor", "implement"}
_HIGH_COMPLEXITY_OBJECTS = {"auth", "database", "infra"}
_MAX_COMPLEXITY_TYPES = {"hard_bugfix"}


def classify_task(features: TaskFeatures) -> TaskLabels:
    """Classify extracted features into task labels."""

    # Artifact type
    artifact_type = _classify_artifact_type(features)

    # Risk domain
    risk_domain = _classify_risk_domain(features)

    # Complexity
    complexity = _classify_complexity(features)

    # Needs code change
    code_change_actions = {"fix", "refactor", "implement"}
    needs_code_change = bool(set(features.actions) & code_change_actions)

    return TaskLabels(
        action=features.actions,
        object=features.objects,
        artifact_type=artifact_type,
        risk_domain=risk_domain,
        complexity=complexity,
        requires_multimodal=features.requires_multimodal,
        explicit_model_request=features.explicit_model_request,
        needs_code_change=needs_code_change,
        task_shape=features.task_shape,
    )


def _classify_artifact_type(features: TaskFeatures) -> str:
    """Determine the primary artifact type."""
    # Docs paths/actions dominate
    if "docs" in features.path_kinds or "docs" in features.actions or "docs" in features.objects:
        return "docs"
    if "tests" in features.path_kinds or "test" in features.actions:
        return "tests"
    if features.requires_multimodal and "ui" in features.objects:
        return "ui_multimodal"
    if features.requires_multimodal:
        return "multimodal"
    if "fix" in features.actions:
        return "bugfix"
    if "refactor" in features.actions:
        return "refactor"
    if "implement" in features.actions:
        return "feature"
    return "general"


def _classify_risk_domain(features: TaskFeatures) -> list[str]:
    """Determine risk domains."""
    if "docs" in features.path_kinds or "docs" in features.actions or "docs" in features.objects:
        return ["docs"]

    domains = []
    high_risk_objects = {"auth", "database", "infra"}

    for obj in features.objects:
        if obj in high_risk_objects:
            # Only high-risk if action is modify/refactor/migrate/delete/deploy
            high_risk_actions = {"refactor", "implement", "fix"}
            if features.actions and bool(set(features.actions) & high_risk_actions):
                domains.append(obj)
            elif features.risk_level == "high":
                domains.append(obj)
        elif obj == "architecture" and "docs" not in features.actions and "docs" not in features.path_kinds:
            domains.append("architecture")

    if not domains:
        domains.append("docs" if "docs" in features.objects or "docs" in features.path_kinds else "general")

    return domains


def _classify_complexity(features: TaskFeatures) -> str:
    """Determine task complexity."""
    if features.task_type in _MAX_COMPLEXITY_TYPES:
        return "max"
    if features.risk_level == "high":
        return "high"
    if features.task_type in {"complex_coding", "large_refactor", "large_context"}:
        return "high"
    if bool(set(features.actions) & _HIGH_COMPLEXITY_ACTIONS) and bool(set(features.objects) & _HIGH_COMPLEXITY_OBJECTS):
        return "high"
    if "docs" in features.actions and "docs" in features.path_kinds:
        return "low"
    if "test" in features.actions:
        return "medium"
    return "medium"
