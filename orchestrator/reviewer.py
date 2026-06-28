from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_codex_review(inputs: dict[str, Any], output_path: Path, timeout: int = 900) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review = _local_review(inputs)
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
                review = parsed
            else:
                review["non_blocking_issues"].append("codex review output was not parseable; used local gate")
        except (OSError, subprocess.TimeoutExpired) as exc:
            review["non_blocking_issues"].append(f"codex review unavailable; used local gate: {exc}")
    output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return review


def _local_review(inputs: dict[str, Any]) -> dict[str, Any]:
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
        "risk_level": inputs.get("risk_level", "medium"),
        "blocking_issues": blocking,
        "non_blocking_issues": [],
        "required_changes": blocking,
        "final_recommendation": "create PR" if approved else "do not create PR",
        "can_create_pr": approved,
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
