from __future__ import annotations

import re
from typing import Any


SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization|bearer)")
SECRET_VALUE_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
ENV_PATH_RE = re.compile(r"(^|[\\/])[^\\/]*\.env($|[\\/])|(^|[\\/])\.env($|[\\/])", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact(item)
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

