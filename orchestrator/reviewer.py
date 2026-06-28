from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_codex_review(inputs: dict[str, Any], output_path: Path, timeout: int = 900) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    risk_level = str(inputs.get("risk_level", "medium")).lower()
    review = _local_review(inputs, degraded=False)
    if inputs.get("dry_run"):
        output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return review
    if shutil.which("codex"):
        prompt = (
            "Review this orchestrator task. Output only JSON with keys "
            "approved,risk_level,blocking_issues,non_blocking_issues,required_changes,"
            "final_recommendation,can_create_pr.\n\n"
            + json.dumps(inputs, ensure_ascii=False)
        )
        try:
            proc = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check", prompt],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            parsed = _extract_json(proc.stdout)
            if parsed:
                review = _normalize_codex_review(parsed, inputs)
            else:
                review = _degraded_review(inputs, "codex review output was not parseable")
        except (OSError, subprocess.TimeoutExpired) as exc:
            review = _degraded_review(inputs, f"codex review unavailable: {exc}")
    else:
        review = _degraded_review(inputs, "codex CLI not found")

    if review.get("degraded") and risk_level in {"medium", "high", "max"}:
        review["approved"] = False
        review["can_create_pr"] = False
        review["required_changes"] = list(review.get("required_changes") or [])
        review["required_changes"].append("Codex review must be available for medium+ risk tasks")
        review["final_recommendation"] = "needs user review; do not publish"

    output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return review


def _local_review(inputs: dict[str, Any], degraded: bool = False, reason: str | None = None) -> dict[str, Any]:
    blocking: list[str] = []
    if not inputs.get("tests_passed", False):
        blocking.append("tests failed or were not run")
    if inputs.get("forbidden_paths_touched"):
        blocking.append("forbidden paths were modified")
    if inputs.get("secret_leak_detected"):
        blocking.append("possible secret leak detected")
    approved = not blocking
    return {
        "approved": approved,
        "review_mode": "local_fallback" if degraded else "local",
        "degraded": degraded,
        "degradation_reason": reason,
        "available": not degraded,
        "risk_level": inputs.get("risk_level", "medium"),
        "blocking_issues": blocking,
        "non_blocking_issues": [reason] if degraded and reason else [],
        "required_changes": blocking,
        "final_recommendation": "create PR" if approved else "do not create PR",
        "can_create_pr": approved,
    }


def _degraded_review(inputs: dict[str, Any], reason: str) -> dict[str, Any]:
    return _local_review(inputs, degraded=True, reason=reason)


def _normalize_codex_review(parsed: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    local = _local_review(inputs, degraded=False)
    review = {**local, **parsed}
    review["review_mode"] = "codex"
    review["degraded"] = False
    review["degradation_reason"] = None
    review["available"] = True
    review["approved"] = bool(review.get("approved")) and not bool(local.get("blocking_issues"))
    if local.get("blocking_issues"):
        review["blocking_issues"] = list(dict.fromkeys([*local["blocking_issues"], *review.get("blocking_issues", [])]))
        review["required_changes"] = list(dict.fromkeys([*local["blocking_issues"], *review.get("required_changes", [])]))
        review["can_create_pr"] = False
    else:
        review["can_create_pr"] = bool(review.get("can_create_pr", review["approved"]))
    return review


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
