from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .display_names import display_agent_name, display_model_name
from .redaction import redact


PUBLIC_ARTIFACTS = {
    "final.md",
    "result.json",
    "review/review.json",
    "verify/verify.json",
    "verify/diff.patch",
    "metrics.json",
    "route.json",
    "approval.json",
    "approval_explanation.md",
    "multimodal/vision_observation.json",
    "task.json",
}


def parse_payload(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError:
        return {"raw": payload_json}
    return value if isinstance(value, dict) else {"value": value}


def task_summary(row: dict[str, Any]) -> dict[str, Any]:
    return redact({
        "task_id": row.get("task_id"),
        "project_id": row.get("project_id"),
        "repo_path": row.get("repo_path"),
        "user_goal": row.get("user_goal"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "route": {
            "worker": display_agent_name(row.get("route_worker")),
            "model": display_model_name(row.get("route_model")),
            "variant": row.get("route_variant"),
        },
        "pr_url": row.get("pr_url"),
    })


def event_view(row: dict[str, Any]) -> dict[str, Any]:
    return redact({
        "id": row.get("id"),
        "task_id": row.get("task_id"),
        "at": row.get("at"),
        "event_type": row.get("event_type"),
        "from_state": row.get("from_state"),
        "to_state": row.get("to_state"),
        "payload": parse_payload(row.get("payload_json")),
    })


def metric_view(row: dict[str, Any]) -> dict[str, Any]:
    value = redact(dict(row))
    value["worker"] = display_agent_name(row.get("worker"))
    value["model"] = display_model_name(row.get("model"))
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
        value[key] = row.get(key)
    return value


def alert_view(row: dict[str, Any]) -> dict[str, Any]:
    return redact(dict(row))


def heartbeat_view(row: dict[str, Any]) -> dict[str, Any]:
    value = redact(dict(row))
    value["model_key"] = display_model_name(row.get("model_key"))
    return value


def artifact_listing(task_id: str, index: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for relative, absolute in sorted(index.items()):
        if not artifact_allowed(relative):
            continue
        items.append({
            "task_id": task_id,
            "path": relative,
            "name": Path(relative).name,
            "url": f"/api/tasks/{task_id}/artifacts/{relative}",
        })
    return items


def artifact_allowed(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lstrip("/")
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        return False
    return normalized in PUBLIC_ARTIFACTS
