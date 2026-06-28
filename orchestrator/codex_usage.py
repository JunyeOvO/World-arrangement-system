from __future__ import annotations

import json
import math
import time
from typing import Any


TOKEN_ESTIMATION_METHOD = "utf8_bytes_div_4"


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def estimate_payload_tokens(payload: Any) -> int:
    if isinstance(payload, str):
        return estimate_text_tokens(payload)
    return estimate_text_tokens(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_codex_usage_event(
    *,
    task_id: str,
    phase: str,
    input_payload: Any,
    output_payload: Any | None = None,
    actual_codex_used: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_tokens = estimate_payload_tokens(input_payload)
    output_tokens = estimate_payload_tokens(output_payload) if output_payload is not None else 0
    return {
        "task_id": task_id,
        "phase": phase,
        "model": "codex",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "actual_codex_used": actual_codex_used,
        "estimation_method": TOKEN_ESTIMATION_METHOD,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": metadata or {},
    }
