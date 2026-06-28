from __future__ import annotations

import re
from typing import Any


SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization|bearer)")
SECRET_VALUE_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
ENV_PATH_RE = re.compile(r"(^|[\\/])[^\\/]*\.env($|[\\/])|(^|[\\/])\.env($|[\\/])", re.IGNORECASE)
PUBLIC_METRIC_KEYS = {
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "total_tokens",
    "missing_token_rows",
    "codex_token_savings_measured",
    "estimated_input_tokens",
    "estimated_output_tokens",
    "estimated_total_tokens",
    "planning_dispatch_tokens",
    "world_review_tokens",
    "actual_codex_review_tokens",
    "actual_codex_event_count",
    "required_codex_reduction_pct",
    "max_codex_share_pct",
}
PUBLIC_TEXT_KEYS = {
    "codex_token_savings_note",
    "estimation_method",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in PUBLIC_METRIC_KEYS and isinstance(item, (bool, int, float)):
                redacted[key_text] = item
            elif key_text in PUBLIC_TEXT_KEYS and isinstance(item, str):
                redacted[key_text] = _redact_text(item)
            elif SECRET_KEY_RE.search(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    text = SECRET_VALUE_RE.sub("[REDACTED]", text)
    if ENV_PATH_RE.search(text):
        return "[REDACTED_PATH]"
    return text
