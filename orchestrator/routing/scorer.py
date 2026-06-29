"""CandidateScorer: score candidate routes against task features."""
from __future__ import annotations

from typing import Any

from .schema import CandidateRoute, TaskFeatures, TaskLabels


# Default score weights (overridable by routing_rules.yaml)
DEFAULT_WEIGHTS = {
    "explicit_model_request": 100,
    "multimodal_required": 80,
    "hard_complexity": 70,
    "hard_bugfix": 75,
    "large_refactor": 70,
    "docs_target": 55,
    "readme_path": 30,
    "test_task": 45,
    "simple_bugfix": 40,
    "low_cost_preference": 25,
    "project_preference": 20,
    "history_success_rate": 20,
    "architecture_keyword": 20,
    "high_risk_object": 25,
    "docs_context_penalty_for_opencode": -40,
    "cost_penalty_glm52": -20,
    "risk_penalty": -50,
}


MIN_HISTORY_ATTEMPTS = 3


def score_candidates(
    candidates: list[CandidateRoute],
    task: dict[str, Any],
    project: dict[str, Any] | None,
    features: TaskFeatures,
    labels: TaskLabels,
    history: list[dict[str, Any]] | dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> list[CandidateRoute]:
    """Score each candidate route against task features."""
    w = weights or DEFAULT_WEIGHTS
    project = project or {}
    history_by_route, model_cost_floor = _normalize_history(history)

    for c in candidates:
        c.base_score = 0.0

        # ── Explicit model request ──
        if features.explicit_model_request == "glm52" and c.worker == "opencode":
            c.base_score += w.get("explicit_model_request", 100)
            c.reasons.append("explicit GLM-5.2 request")

        # ── Multimodal ──
        if features.requires_multimodal and c.model in {"mimo_v25", "mimo_v25_pro"}:
            c.base_score += w.get("multimodal_required", 80)
            c.reasons.append("multimodal task match")

        # ── Complexity ──
        if labels.complexity == "max" and c.intensity == "max":
            c.base_score += w.get("hard_bugfix", 75)
            c.reasons.append("max intensity for hard_bugfix")
        elif labels.complexity == "high" and c.intensity in ("high", "max"):
            c.base_score += w.get("hard_complexity", 70)
            c.reasons.append("high complexity match")
        elif labels.complexity == "medium" and c.intensity == "medium":
            c.base_score += 30

        # ── Docs target ──
        if labels.artifact_type == "docs" and c.worker == "claude_code":
            c.base_score += w.get("docs_target", 55)
            c.reasons.append("docs task -> ClaudeCodeWorker")
            # deepseek_pro is default for docs, not flash
            if c.model == "deepseek_pro":
                c.base_score += 5
                c.reasons.append("deepseek_pro default for docs")

        # ── README path bonus ──
        if "readme" in features.goal_lower and c.worker == "claude_code":
            c.base_score += w.get("readme_path", 30)
            c.reasons.append("README path -> ClaudeCodeWorker")

        # ── Test task ──
        if labels.artifact_type == "tests" and c.worker == "claude_code":
            c.base_score += w.get("test_task", 45)
            c.reasons.append("test task -> ClaudeCodeWorker")

        # ── Low cost preference for simple tasks (only when project prefers) ──
        # Flash is NOT the default for docs; deepseek_pro is default
        project = project or {}
        if labels.complexity == "low" and c.model == "deepseek_flash" and project.get("prefer_low_cost_for_docs"):
            c.base_score += w.get("low_cost_preference", 25)
            c.reasons.append("low cost preferred for simple task")

        # ── Default model bonus: deepseek_pro over flash for non-trivial tasks ──
        if c.model == "deepseek_pro" and labels.complexity != "low":
            c.base_score += 10
        if c.model == "deepseek_flash" and labels.complexity in ("high", "max"):
            c.base_score -= 5
            c.penalties.append("flash not suitable for high complexity")

        # ── Architecture keyword ──
        if "architecture" in features.objects:
            if labels.artifact_type == "docs":
                # Architecture keyword in docs context = docs, not high-risk
                if c.worker == "opencode":
                    c.base_score += w.get("docs_context_penalty_for_opencode", -40)
                    c.penalties.append("architecture keyword in docs context -> penalize OpenCode")
            else:
                if c.worker == "opencode":
                    c.base_score += w.get("architecture_keyword", 20)
                    c.reasons.append("architecture refactor -> OpenCode")

        # ── High risk objects ──
        high_risk_objects = {"auth", "database", "infra"}
        if set(features.objects) & high_risk_objects:
            if labels.needs_code_change:
                if c.worker == "opencode" and "docs" not in labels.action:
                    c.base_score += w.get("high_risk_object", 25)
                    c.reasons.append("high-risk object modification")

        # ── Docs context penalty for OpenCode ──
        if labels.artifact_type == "docs" and c.worker == "opencode":
            c.base_score += w.get("docs_context_penalty_for_opencode", -40)
            c.penalties.append("docs context -> OpenCode overkill")

        # ── GLM-5.2 cost penalty ──
        if "glm" in c.model.lower() and labels.complexity in ("low", "medium") and labels.artifact_type != "general":
            c.base_score += w.get("cost_penalty_glm52", -20)
            c.penalties.append("GLM-5.2 cost penalty for non-complex task")

        # ── Project preference ──
        if project.get("default_worker") == c.worker:
            c.base_score += w.get("project_preference", 20)
            c.reasons.append(f"project default worker: {c.worker}")
        if project.get("default_model") == c.model:
            c.base_score += w.get("project_preference", 20)
            c.reasons.append(f"project default model: {c.model}")

        # ── Historical cost/success signal ──
        history_item = history_by_route.get((c.worker, c.model)) or history_by_route.get(("", c.model))
        if history_item:
            adjustment = _history_adjustment(history_item, model_cost_floor, w.get("history_success_rate", 20))
            if adjustment:
                c.base_score += adjustment
                c.reasons.append(
                    "history-aware route: "
                    f"attempts={history_item.get('attempts')}, "
                    f"success_rate={history_item.get('success_rate')}, "
                    f"avg_cost={history_item.get('avg_cost')}, "
                    f"score_delta={adjustment:+.1f}"
                )

        c.score = c.base_score

    # Sort by score descending
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates


def _normalize_history(
    history: list[dict[str, Any]] | dict[str, Any] | None,
) -> tuple[dict[tuple[str, str], dict[str, Any]], float | None]:
    rows: list[dict[str, Any]] = []
    if not history:
        return {}, None
    if isinstance(history, dict):
        for model, item in history.items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("model", model)
                rows.append(row)
        if not rows and history.get("model"):
            rows.append(history)
    else:
        rows = [row for row in history if isinstance(row, dict)]

    result: dict[tuple[str, str], dict[str, Any]] = {}
    costs: list[float] = []
    for row in rows:
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        worker = str(row.get("worker") or "").strip()
        item = {
            "worker": worker or None,
            "model": model,
            "attempts": _int_or_none(row.get("attempts")),
            "success_rate": _float_or_none(row.get("success_rate")),
            "avg_cost": _float_or_none(row.get("avg_cost_usd") if "avg_cost_usd" in row else row.get("avg_cost")),
        }
        if item["avg_cost"] is not None:
            costs.append(float(item["avg_cost"]))
        result[(worker, model)] = item
        result.setdefault(("", model), item)
    return result, min(costs) if costs else None


def _history_adjustment(item: dict[str, Any], cost_floor: float | None, max_success_weight: float) -> float:
    success_rate = _float_or_none(item.get("success_rate"))
    if success_rate is None:
        return 0.0
    attempts = _int_or_none(item.get("attempts"))
    if attempts is None:
        evidence_weight = 0.5
    elif attempts <= 0:
        return 0.0
    else:
        evidence_weight = min(1.0, attempts / 10.0)
        if attempts < MIN_HISTORY_ATTEMPTS:
            evidence_weight *= 0.35

    success_delta = (success_rate - 0.75) * max_success_weight * 2.0 * evidence_weight
    cost_delta = 0.0
    avg_cost = _float_or_none(item.get("avg_cost"))
    if cost_floor is not None and avg_cost is not None and avg_cost > 0:
        relative_over_floor = max(0.0, (avg_cost - cost_floor) / avg_cost)
        cost_delta = -min(8.0, relative_over_floor * 10.0) * evidence_weight
    return round(success_delta + cost_delta, 2)


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
