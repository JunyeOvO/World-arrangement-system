from __future__ import annotations

from typing import Any

from .llm_capability import capability_profile, normalize_capability_tier


RETRYABLE_FAILURES = {"worker_failed", "tests_failed", "patch_failed", "command_timeout", "failed"}
NON_RETRYABLE_FAILURES = {
    "forbidden_path",
    "dangerous_command",
    "secret_exposure",
    "approval_rejected",
    "blocked",
    "cancelled",
}


def build_retry_chain(route: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the worker attempt chain from a route's escalation plan."""
    route_retry_chain = route.get("retry_chain")
    if isinstance(route_retry_chain, list) and route_retry_chain:
        chain = []
        for idx, item in enumerate(route_retry_chain):
            if not isinstance(item, dict):
                continue
            model = item.get("model") or item.get("selected_model") or "deepseek_pro"
            worker = item.get("worker") or item.get("selected_worker") or "claude_code"
            tier = normalize_capability_tier(item.get("capability_tier"), item.get("intensity"))
            chain.append(
                {
                    "worker": worker,
                    "model": model,
                    "variant": item.get("variant"),
                    "capability_tier": tier,
                    "capability_profile": item.get("capability_profile")
                    or capability_profile(model, tier, item.get("intensity")),
                    "reason": item.get("reason")
                    or ("primary attempt" if idx == 0 else item.get("condition", "route retry")),
                    "status": "",
                }
            )
        if chain:
            return chain

    chain: list[dict[str, Any]] = [
        {
            "worker": route.get("selected_worker", "claude_code"),
            "model": route.get("selected_model", "deepseek_pro"),
            "variant": route.get("variant"),
            "capability_tier": route.get("capability_tier"),
            "capability_profile": route.get("capability_profile"),
            "reason": "primary attempt",
            "status": "",
        }
    ]

    fallback_models = route.get("fallback_models", [])
    if isinstance(fallback_models, list):
        for fallback in fallback_models:
            if isinstance(fallback, str):
                tier = normalize_capability_tier(None, "medium")
                chain.append(
                    {
                        "worker": "claude_code",
                        "model": fallback,
                        "variant": None,
                        "capability_tier": tier,
                        "capability_profile": capability_profile(fallback, tier, "medium"),
                        "reason": f"fallback to {fallback}",
                        "status": "",
                    }
                )
            elif isinstance(fallback, dict):
                tier = normalize_capability_tier(fallback.get("capability_tier"), fallback.get("intensity"))
                model = fallback.get("model", "deepseek_pro")
                chain.append(
                    {
                        "worker": fallback.get("worker", "claude_code"),
                        "model": model,
                        "variant": fallback.get("variant"),
                        "capability_tier": tier,
                        "capability_profile": capability_profile(model, tier, fallback.get("intensity")),
                        "reason": fallback.get("reason", f"escalation to {fallback.get('model', 'unknown')}"),
                        "status": "",
                    }
                )

    if route.get("escalation_policy") == "opencode_on_failure":
        has_opencode = any(attempt["worker"] == "opencode" for attempt in chain)
        if not has_opencode:
            chain.append(
                {
                    "worker": "opencode",
                    "model": "opencode_go_glm52",
                    "variant": "high",
                    "capability_tier": "high",
                    "capability_profile": capability_profile("opencode_go_glm52", "high", "high"),
                    "reason": "ClaudeCodeWorker failed; escalate to GLM-5.2 high",
                    "status": "",
                }
            )
            chain.append(
                {
                    "worker": "opencode",
                    "model": "opencode_go_glm52",
                    "variant": "max",
                    "capability_tier": "max",
                    "capability_profile": capability_profile("opencode_go_glm52", "max", "max"),
                    "reason": "GLM-5.2 high failed; escalate to max",
                    "status": "",
                }
            )

    return chain


def is_retryable_failure(result: Any) -> bool:
    status = getattr(result, "status", "failed")
    if status in NON_RETRYABLE_FAILURES or status == "blocked":
        return False
    return status in RETRYABLE_FAILURES or status == "failed"


def should_recover_failed_worker_diff(result: Any) -> bool:
    if getattr(result, "status", "") != "failed":
        return False
    return bool(getattr(result, "changed_files", []))
