from __future__ import annotations

import re
from typing import Any

from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier


TASK_SHAPES = {
    "targeted_patch",
    "open_bug_hunt",
    "docs_update",
    "test_generation",
    "large_refactor",
    "multimodal_analysis",
    "multimodal_to_code",
    "config_repair",
    "review_only",
}

_MODEL_COST_ESTIMATES = {
    "deepseek_flash": 0.08,
    "deepseek_pro": 0.30,
    "mimo_v25": 0.20,
    "mimo_v25_pro": 0.40,
    "opencode-go/glm-5.2": 0.55,
    "opencode_go_glm52": 0.55,
}


def classify_task_shape(task: dict[str, Any], features: Any | None = None, labels: Any | None = None) -> str:
    explicit = str(task.get("task_shape") or "").strip()
    if explicit in TASK_SHAPES:
        return explicit

    goal = str(task.get("user_goal", ""))
    lower = goal.lower()
    target_paths = [str(p).lower() for p in task.get("target_paths", [])]
    task_type = str(task.get("task_type", "")).lower()
    requires_multimodal = bool(getattr(features, "requires_multimodal", False))
    needs_code_change = bool(getattr(labels, "needs_code_change", False))

    if requires_multimodal and needs_code_change:
        return "multimodal_to_code"
    if requires_multimodal:
        return "multimodal_analysis"
    if task_type == "hard_bugfix":
        return "large_refactor"
    if task_type in {"large_refactor", "large_context"} or _has_phrase(lower, ["large refactor", "大规模重构", "重构整个", "rewrite entire"]):
        return "large_refactor"
    if _is_review_only(lower):
        return "review_only"
    if _is_config_repair(lower, target_paths):
        return "config_repair"
    if _is_test_generation(lower):
        return "test_generation"
    if _is_docs_update(lower, target_paths):
        return "docs_update"
    if _is_open_bug_hunt(lower, task):
        return "open_bug_hunt"
    if _is_targeted_patch(lower, target_paths, task_type):
        return "targeted_patch"
    if needs_code_change:
        return "targeted_patch"
    return "review_only" if "analyze" in lower or "分析" in lower else "targeted_patch"


def apply_router_v3(
    route: dict[str, Any],
    task: dict[str, Any],
    project: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | dict[str, Any] | None = None,
    features: Any | None = None,
    labels: Any | None = None,
) -> dict[str, Any]:
    project = project or {}
    task_shape = classify_task_shape(task, features, labels)
    history_basis = _normalize_history(history)
    budget_cap = _float_or_none(task.get("budget_cap_usd") or project.get("budget_cap_usd"))
    route = dict(route)
    if route.get("blocked"):
        route["task_shape"] = task_shape
        route["budget_estimate_usd"] = 0.0
        route["budget_cap_usd"] = budget_cap
        route["history_basis"] = history_basis
        task_labels = dict(route.get("task_labels") or {})
        task_labels["task_shape"] = task_shape
        route["task_labels"] = task_labels
        route["retry_chain"] = []
        route["fallback_models"] = []
        route["reason"] = f"{route.get('reason', 'BLOCKED')}; task_shape={task_shape}; budget_estimate_usd=0.00"
        return route

    selected = _select_for_shape(task_shape, route, task, project, history_basis, budget_cap)
    if selected:
        route.update(selected)

    retry_chain = _retry_chain_for_shape(task_shape, route)
    route["retry_chain"] = retry_chain
    route["fallback_models"] = _fallback_models(retry_chain)
    route["max_retries"] = max(0, len(retry_chain) - 1)
    route["escalation_policy"] = "opencode_on_failure" if any(s["worker"] == "opencode" for s in retry_chain[1:]) else route.get("escalation_policy", "codex_review_or_needs_user")

    estimate = _estimate_route_cost(retry_chain)
    route["task_shape"] = task_shape
    route["budget_estimate_usd"] = estimate
    route["budget_cap_usd"] = budget_cap
    route["history_basis"] = history_basis
    route["reason"] = _reason(route, task_shape, history_basis, budget_cap, estimate)
    route["agent_llm"] = agent_llm_name(str(route.get("selected_worker", "")), str(route.get("selected_model", "")))
    task_labels = dict(route.get("task_labels") or {})
    task_labels["task_shape"] = task_shape
    route["task_labels"] = task_labels
    route["capability_tier"] = normalize_capability_tier(route.get("capability_tier"), route.get("intensity"))
    route["capability_profile"] = route.get("capability_profile") or capability_profile(
        route.get("selected_model", ""),
        route.get("capability_tier"),
        route.get("intensity"),
    )
    return route


def _select_for_shape(
    task_shape: str,
    route: dict[str, Any],
    task: dict[str, Any],
    project: dict[str, Any],
    history: dict[str, Any],
    budget_cap: float | None,
) -> dict[str, Any] | None:
    if route.get("blocked"):
        return None

    explicit_model = str(task.get("force_model") or route.get("selected_model") or "").lower()
    goal = str(task.get("user_goal", "")).lower()
    task_type = str(task.get("task_type", "")).lower()
    if task_type == "hard_bugfix":
        return _opencode("max")
    if route.get("selected_worker") == "opencode" or project.get("default_worker") == "opencode":
        if project.get("default_worker") == "opencode" and task_type not in {"complex_coding"} and "glm" not in goal:
            variant = _normalize_variant(project.get("default_variant"))
        else:
            variant = _normalize_variant(route.get("variant"))
            if not variant and route.get("selected_model") == "opencode-go/glm-5.2":
                variant = _normalize_variant(project.get("default_variant"))
        return _opencode(variant) if variant else _opencode_without_variant()
    if "glm" in explicit_model or "glm" in goal:
        return _opencode("high")

    if task_shape == "docs_update":
        project_prefers_flash = route.get("selected_model") == "deepseek_flash"
        model = "deepseek_flash" if (
            project_prefers_flash
            or (_history_ok(history, "deepseek_flash") and _within_budget("deepseek_flash", budget_cap))
        ) else "deepseek_pro"
        return _claude(model, "low" if model == "deepseek_flash" else "medium")
    if task_shape == "open_bug_hunt":
        return _claude("deepseek_pro", "high")
    if task_shape == "targeted_patch":
        target_model = "deepseek_pro"
        if _single_file_target(task) and _history_ok(history, "deepseek_flash") and _within_budget("deepseek_flash", budget_cap):
            target_model = "deepseek_flash"
        return _claude(target_model, "medium" if target_model == "deepseek_pro" else "low")
    if task_shape == "test_generation":
        return _claude("deepseek_pro", "medium")
    if task_shape == "large_refactor":
        return _opencode("max")
    if task_shape == "multimodal_analysis":
        return _claude("mimo_v25", "medium")
    if task_shape == "multimodal_to_code":
        return _claude("mimo_v25_pro", "high")
    if task_shape == "config_repair":
        return _claude("deepseek_pro", "medium")
    if task_shape == "review_only":
        return _claude("deepseek_pro", "medium")
    return None


def _retry_chain_for_shape(task_shape: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    primary = _step(
        str(route.get("selected_worker") or "claude_code"),
        str(route.get("selected_model") or "deepseek_pro"),
        route.get("variant"),
        str(route.get("intensity") or "medium"),
        "primary task_shape route",
    )
    if task_shape == "docs_update":
        fallback = "deepseek_pro" if primary["model"] == "deepseek_flash" else "deepseek_flash"
        return [primary, _step("claude_code", fallback, None, "medium", "docs_update fallback")]
    if task_shape == "targeted_patch":
        chain = [primary]
        if primary["model"] != "deepseek_pro":
            chain.append(_step("claude_code", "deepseek_pro", None, "medium", "targeted_patch stronger fallback"))
        chain.append(_step("opencode", "opencode-go/glm-5.2", "high", "high", "targeted_patch opencode fallback"))
        return chain
    if task_shape in {"open_bug_hunt", "test_generation", "config_repair", "multimodal_to_code"}:
        return [primary, _step("opencode", "opencode-go/glm-5.2", "high", "high", f"{task_shape} fallback")]
    if task_shape == "large_refactor":
        if primary["worker"] == "opencode" and primary.get("variant") == "max":
            return [
                primary,
                _step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor high fallback"),
            ]
        return [primary, _step("opencode", "opencode-go/glm-5.2", "high", "high", "large_refactor fallback")]
    if task_shape == "multimodal_analysis":
        return [primary, _step("claude_code", "mimo_v25_pro", None, "high", "multimodal_analysis pro fallback")]
    return [primary]


def _normalize_history(history: list[dict[str, Any]] | dict[str, Any] | None) -> dict[str, Any]:
    if not history:
        return {}
    if isinstance(history, dict):
        return history
    result: dict[str, Any] = {}
    for row in history:
        model = str(row.get("model") or "")
        if not model:
            continue
        result[model] = {
            "success_rate": _float_or_none(row.get("success_rate")),
            "avg_cost": _float_or_none(row.get("avg_cost_usd") if "avg_cost_usd" in row else row.get("avg_cost")),
            "attempts": row.get("attempts"),
            "worker": row.get("worker"),
        }
    return result


def _reason(route: dict[str, Any], task_shape: str, history: dict[str, Any], budget_cap: float | None, estimate: float) -> str:
    selected_model = str(route.get("selected_model", ""))
    parts = [
        f"task_shape={task_shape}",
        f"selected={route.get('selected_worker')}/{selected_model}",
        f"budget_estimate_usd={estimate:.2f}",
    ]
    if budget_cap is not None:
        parts.append(f"budget_cap_usd={budget_cap:.2f}")
    if selected_model in history:
        item = history[selected_model]
        parts.append(
            f"history[{selected_model}].success_rate={item.get('success_rate')}; avg_cost={item.get('avg_cost')}"
        )
    elif history:
        parts.append("history=no_selected_model_record")
    else:
        parts.append("history=no_prior_metrics")
    if task_shape == "open_bug_hunt" and selected_model == "deepseek_pro":
        parts.append("open bug hunt avoids flash as primary")
    fallback = [s["model"] for s in route.get("retry_chain", [])[1:]]
    if fallback:
        parts.append(f"fallback={fallback}")
    return "; ".join(parts)


def _estimate_route_cost(chain: list[dict[str, Any]]) -> float:
    total = 0.0
    for idx, step in enumerate(chain):
        multiplier = 1.0 if idx == 0 else 0.35
        total += _MODEL_COST_ESTIMATES.get(str(step.get("model")), 0.30) * multiplier
    return round(total, 4)


def _fallback_models(chain: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for step in chain[1:]:
        model = str(step.get("model", ""))
        if model and model not in seen:
            seen.append(model)
    return seen


def _claude(model: str, intensity: str) -> dict[str, Any]:
    tier = normalize_capability_tier(None, intensity)
    return {
        "selected_worker": "claude_code",
        "selected_agent": "claude_code",
        "selected_model": model,
        "selected_llm": model,
        "intensity": intensity,
        "variant": None,
        "capability_tier": tier,
        "capability_profile": capability_profile(model, tier, intensity),
    }


def _opencode(variant: str) -> dict[str, Any]:
    return {
        "selected_worker": "opencode",
        "selected_agent": "opencode",
        "selected_model": "opencode-go/glm-5.2",
        "selected_llm": "opencode-go/glm-5.2",
        "intensity": variant,
        "variant": variant,
        "capability_tier": variant,
        "capability_profile": capability_profile("opencode-go/glm-5.2", variant, variant),
    }


def _opencode_without_variant() -> dict[str, Any]:
    tier = normalize_capability_tier(None, "medium")
    return {
        "selected_worker": "opencode",
        "selected_agent": "opencode",
        "selected_model": "opencode-go/glm-5.2",
        "selected_llm": "opencode-go/glm-5.2",
        "intensity": "medium",
        "variant": None,
        "capability_tier": tier,
        "capability_profile": capability_profile("opencode-go/glm-5.2", tier, "medium"),
    }


def _normalize_variant(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "default"}:
        return None
    if text in {"high", "max", "minimal"}:
        return text
    return None


def _step(worker: str, model: str, variant: str | None, intensity: str, reason: str) -> dict[str, Any]:
    tier = normalize_capability_tier(variant if worker == "opencode" else None, intensity)
    return {
        "worker": worker,
        "model": model,
        "variant": variant,
        "intensity": intensity,
        "capability_tier": tier,
        "capability_profile": capability_profile(model, tier, intensity),
        "reason": reason,
    }


def _is_docs_update(lower: str, target_paths: list[str]) -> bool:
    if any(p.endswith((".md", ".markdown")) or p == "readme.md" or p.startswith("docs/") for p in target_paths):
        return True
    return _has_phrase(lower, ["readme", "markdown", "文档", "documentation", "docs update", "update docs"])


def _is_test_generation(lower: str) -> bool:
    if _has_phrase(lower, ["test run", "test runs", "tests run", "pytest run", "run tests", "test failure", "tests failed"]):
        return False
    return bool(re.search(r"\b(add|write|create|generate|新增|编写|添加)\s+.*\b(unit\s+)?tests?\b", lower)) or _has_phrase(lower, ["测试生成", "生成测试", "补测试"])


def _is_open_bug_hunt(lower: str, task: dict[str, Any]) -> bool:
    if task.get("target_paths"):
        return False
    phrases = [
        "find one bug and fix",
        "find a bug and fix",
        "find bug",
        "hunt bug",
        "open bug",
        "找一个 bug",
        "找一个bug",
        "查找 bug",
        "找 bug 并修复",
    ]
    return _has_phrase(lower, phrases)


def _is_targeted_patch(lower: str, target_paths: list[str], task_type: str) -> bool:
    if target_paths:
        return True
    if task_type in {"simple_bugfix", "routine_coding"}:
        return True
    return _has_phrase(lower, ["fix", "修复", "修改", "update", "change", "implement", "新增", "实现"])


def _is_config_repair(lower: str, target_paths: list[str]) -> bool:
    if any(p.endswith((".yaml", ".yml", ".toml", ".json", ".ini")) or "config" in p for p in target_paths):
        return True
    return _has_phrase(lower, ["config", "configuration", "配置", "settings"])


def _is_review_only(lower: str) -> bool:
    return _has_phrase(lower, ["review only", "audit only", "analyze only", "只分析", "只审查", "不要修改"])


def _single_file_target(task: dict[str, Any]) -> bool:
    target_paths = task.get("target_paths") or []
    return isinstance(target_paths, list) and len(target_paths) == 1


def _history_ok(history: dict[str, Any], model: str) -> bool:
    item = history.get(model)
    if not item:
        return False
    success_rate = _float_or_none(item.get("success_rate"))
    if success_rate is None:
        return False
    return success_rate >= 0.75


def _within_budget(model: str, budget_cap: float | None) -> bool:
    return budget_cap is None or _MODEL_COST_ESTIMATES.get(model, 0.30) <= budget_cap


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _has_phrase(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)
