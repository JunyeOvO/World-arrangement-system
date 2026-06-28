"""CandidateBuilder: generate candidate routes from task features and labels."""
from __future__ import annotations

from typing import Any

from .schema import CandidateRoute, TaskFeatures, TaskLabels


def build_candidates(
    task: dict[str, Any],
    project: dict[str, Any] | None,
    features: TaskFeatures,
    labels: TaskLabels,
) -> list[CandidateRoute]:
    """Build candidate routes based on task features and labels."""
    candidates: list[CandidateRoute] = []

    project = project or {}
    risk_level = features.risk_level

    # ── Candidate 1: ClaudeCodeWorker + DeepSeek Pro (default) ──
    candidates.append(CandidateRoute(
        worker="claude_code", model="deepseek_pro",
        intensity="medium", variant=None,
        reasons=["default worker for routine tasks"],
    ))

    # ── Candidate 2: ClaudeCodeWorker + DeepSeek Flash (low cost) ──
    candidates.append(CandidateRoute(
        worker="claude_code", model="deepseek_flash",
        intensity="low", variant=None,
        reasons=["lowest cost option"],
    ))

    # ── Candidate 3: ClaudeCodeWorker + MiMo V2.5 ──
    if features.requires_multimodal or "ui" in features.objects:
        candidates.append(CandidateRoute(
            worker="claude_code", model="mimo_v25",
            intensity="medium", variant=None,
            reasons=["Claude Code + MiMo V2.5 for multimodal/UI task"],
        ))

    # ── Candidate 4: ClaudeCodeWorker + MiMo V2.5 Pro for multimodal coding ──
    if features.requires_multimodal and labels.needs_code_change:
        candidates.append(CandidateRoute(
            worker="claude_code", model="mimo_v25_pro",
            intensity="high", variant=None,
            reasons=["Claude Code + MiMo V2.5 Pro for multimodal code change"],
        ))

    # ── Candidate 5: OpenCodeWorker + GLM-5.2 high ──
    if (
        features.explicit_model_request == "glm52"
        or labels.complexity in ("high", "max")
        or "architecture" in features.objects
    ):
        variant = "max" if labels.complexity == "max" else "high"
        candidates.append(CandidateRoute(
            worker="opencode", model="opencode-go/glm-5.2",
            intensity="high", variant=variant,
            reasons=["GLM-5.2 for complex/high-intensity tasks"],
        ))

    # ── Candidate 6: OpenCodeWorker + GLM-5.2 max (hard bugfix) ──
    if features.task_type == "hard_bugfix" or labels.complexity == "max":
        candidates.append(CandidateRoute(
            worker="opencode", model="opencode-go/glm-5.2",
            intensity="max", variant="max",
            reasons=["maximum intensity for hard bugfix"],
        ))

    return candidates
