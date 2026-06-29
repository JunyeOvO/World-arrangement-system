from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .codex_usage import TOKEN_ESTIMATION_METHOD, estimate_payload_tokens


BASELINE_KIND_CODEX_ONLY_REPLAY = "codex_only_replay"
REPLAY_BASELINE_ARTIFACT_ALLOWLIST = {
    "task.json",
    "route.json",
    "result.json",
    "verify/verify.json",
    "review/review.json",
    "final.md",
    "metrics.json",
    "token_ledger.json",
    "outcome.json",
}
REPLAY_BASELINE_RUNTIME_PREFIXES = (
    "worktrees/",
    "worker/",
    "control/",
    "attempts/",
)


def build_replay_baseline(
    *,
    task: dict[str, Any],
    artifact_index: dict[str, str],
    baseline_kind: str = BASELINE_KIND_CODEX_ONLY_REPLAY,
) -> dict[str, Any]:
    input_payload = {
        "baseline_prompt": (
            "Estimate the Codex-only effort needed to complete the same task without "
            "World worker delegation. This is a replay accounting record, not an execution."
        ),
        "task": {
            "task_id": task.get("task_id"),
            "project_id": task.get("project_id"),
            "repo_path": task.get("repo_path"),
            "user_goal": task.get("user_goal"),
            "terminal_status": task.get("status"),
            "route_worker": task.get("route_worker"),
            "route_model": task.get("route_model"),
        },
        "artifacts": {
            "task": _read_json_artifact(artifact_index, "task.json"),
            "route": _read_json_artifact(artifact_index, "route.json"),
            "result": _read_json_artifact(artifact_index, "result.json"),
            "verify": _read_json_artifact(artifact_index, "verify/verify.json"),
            "review": _read_json_artifact(artifact_index, "review/review.json"),
        },
        "final_output_excerpt": _read_text_artifact(artifact_index, "final.md", limit=12000),
    }
    output_payload = {
        "expected_codex_response": _read_text_artifact(artifact_index, "final.md", limit=20000),
    }
    input_tokens = estimate_payload_tokens(input_payload)
    output_tokens = estimate_payload_tokens(output_payload)
    return {
        "task_id": task.get("task_id"),
        "baseline_kind": baseline_kind,
        "source": "replay_estimate",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "actual_codex_used": False,
        "estimation_method": TOKEN_ESTIMATION_METHOD,
        "created_at": _now(),
        "metadata": {
            "artifact_paths": _baseline_artifact_paths(artifact_index),
            "artifact_count": len(artifact_index),
            "excluded_runtime_artifact_count": _excluded_runtime_artifact_count(artifact_index),
            "warning": (
                "Replay baseline estimates same-task Codex-only context from stored artifacts. "
                "It is useful for trend analysis but is not measured Codex quota usage."
            ),
        },
    }


def build_manual_baseline(
    *,
    task_id: str,
    input_tokens: int,
    output_tokens: int,
    baseline_kind: str = "codex_only_actual",
    actual_codex_used: bool = True,
    source: str = "manual",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_tokens = max(0, int(input_tokens))
    output_tokens = max(0, int(output_tokens))
    return {
        "task_id": task_id,
        "baseline_kind": baseline_kind,
        "source": source,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "actual_codex_used": bool(actual_codex_used),
        "estimation_method": "manual_actual" if actual_codex_used else "manual_estimate",
        "created_at": _now(),
        "metadata": metadata or {},
    }


def _read_json_artifact(index: dict[str, str], relative: str) -> Any:
    path = index.get(relative)
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return value


def _baseline_artifact_paths(index: dict[str, str]) -> list[str]:
    return sorted(
        key
        for key in index
        if key in REPLAY_BASELINE_ARTIFACT_ALLOWLIST and not key.startswith(REPLAY_BASELINE_RUNTIME_PREFIXES)
    )


def _excluded_runtime_artifact_count(index: dict[str, str]) -> int:
    return sum(1 for key in index if key.startswith(REPLAY_BASELINE_RUNTIME_PREFIXES))


def _read_text_artifact(index: dict[str, str], relative: str, limit: int) -> str:
    path = index.get(relative)
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
