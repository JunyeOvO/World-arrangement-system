from __future__ import annotations

import re
from typing import Any


MODEL_DISPLAY_NAMES = {
    "deepseek_flash": "Deepseek-V4-flash",
    "deepseek-v4-flash": "Deepseek-V4-flash",
    "deepseek_pro": "Deepseek-V4-pro",
    "deepseek-v4-pro": "Deepseek-V4-pro",
    "deepseek-v4-pro[1m]": "Deepseek-V4-pro",
    "mimo_v25": "Mimo-V2.5",
    "mimo-v2.5": "Mimo-V2.5",
    "mimo_v25_pro": "Mimo-V2.5-pro",
    "mimo-v2.5-pro": "Mimo-V2.5-pro",
    "opencode-go/glm-5.2": "GLM-5.2",
    "opencode_go_glm52": "GLM-5.2",
    "glm-5.2": "GLM-5.2",
    "glm": "GLM-5.2",
}

AGENT_DISPLAY_NAMES = {
    "opencode": "Opencode",
    "open_code": "Opencode",
    "opencodeworker": "Opencode",
    "go": "Opencode",
    "claude_code": "Claudecode",
    "claude code": "Claudecode",
    "claudecode": "Claudecode",
    "claudecodeworker": "Claudecode",
}

MODEL_KEYS = {
    "model",
    "models",
    "route_model",
    "selected_model",
    "selected_llm",
    "agent_llm",
    "model_key",
    "fallback_models",
}

AGENT_KEYS = {
    "worker",
    "route_worker",
    "selected_worker",
    "selected_agent",
    "agent",
}

DISPLAY_TEXT_REPLACEMENTS = (
    ("opencode-go/glm-5.2", "GLM-5.2"),
    ("opencode_go_glm52", "GLM-5.2"),
    ("deepseek-v4-pro[1m]", "Deepseek-V4-pro"),
    ("deepseek_flash", "Deepseek-V4-flash"),
    ("deepseek-v4-flash", "Deepseek-V4-flash"),
    ("deepseek_pro", "Deepseek-V4-pro"),
    ("deepseek-v4-pro", "Deepseek-V4-pro"),
    ("deepseek V4 flash", "Deepseek-V4-flash"),
    ("deepseek V4 pro", "Deepseek-V4-pro"),
    ("mimo_v25_pro", "Mimo-V2.5-pro"),
    ("mimo-v2.5-pro", "Mimo-V2.5-pro"),
    ("mimo V2.5 pro", "Mimo-V2.5-pro"),
    ("mimo_v25", "Mimo-V2.5"),
    ("mimo-v2.5", "Mimo-V2.5"),
    ("mimo V2.5", "Mimo-V2.5"),
    ("glm-5.2", "GLM-5.2"),
    ("claude code", "Claudecode"),
    ("ClaudeCodeWorker", "Claudecode"),
    ("claude_code", "Claudecode"),
    ("opencodeworker", "Opencode"),
    ("opencode", "Opencode"),
)


def display_model_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return MODEL_DISPLAY_NAMES.get(value.strip().lower(), value)


def display_agent_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return AGENT_DISPLAY_NAMES.get(value.strip().lower(), value)


def display_known_terms(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    display = value
    for source, replacement in DISPLAY_TEXT_REPLACEMENTS:
        display = re.sub(re.escape(source), replacement, display, flags=re.IGNORECASE)
    return display


def display_route_value(key: str, value: Any) -> Any:
    normalized = key.strip().lower()
    if normalized in MODEL_KEYS or normalized.endswith("_model"):
        if isinstance(value, list):
            return [display_model_name(item) for item in value]
        return display_model_name(display_known_terms(value))
    if normalized in AGENT_KEYS or normalized.endswith("_worker") or normalized.endswith("_agent"):
        if isinstance(value, list):
            return [display_agent_name(item) for item in value]
        return display_agent_name(display_known_terms(value))
    return display_known_terms(value)


def display_route_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: display_route_value(str(key), display_route_tree(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [display_route_tree(item) for item in value]
    return value
