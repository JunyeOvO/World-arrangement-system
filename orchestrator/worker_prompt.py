from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .config import code_root
from .worker_prompt_profiles import read_only_required_output_contract, worker_profile_strategy


_OPENCODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "opencode_worker_prompt.md"
_CLAUDE_CODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "claude_code_worker_prompt.md"


def build_worker_prompt(
    task: dict[str, Any],
    route: dict[str, Any],
    *,
    task_requires_diff: Callable[[dict[str, Any]], bool],
) -> str:
    worker = str(route.get("selected_worker", "")).lower()
    read_only = not task_requires_diff(task)
    read_only_completion_rule = ""
    if read_only:
        read_only_completion_rule = (
            "Read-only completion rule: produce a concise partial result before the read budget is exhausted. "
            "If you are near the turn or time limit, stop exploring and return the best current answer with "
            "changed_files=[] instead of making more tool calls.\n"
        )
    required_output = read_only_required_output_contract(task, read_only=read_only)
    profile_strategy = worker_profile_strategy(task)
    project_memory = _project_memory_section(task)
    task_section = (
        f"\n\n## Task Context\n\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        f"Worktree: {task.get('worktree_path', '')}\n"
        f"Risk level: {task.get('risk_level', 'medium')}\n"
        f"Test commands: {json.dumps(task.get('test_commands', []), ensure_ascii=False)}\n"
        f"Build commands: {json.dumps(task.get('build_commands', []), ensure_ascii=False)}\n"
        f"Forbidden paths: {json.dumps(task.get('forbidden_paths', []), ensure_ascii=False)}\n"
        f"Task mode: {task.get('task_mode', 'patch')}\n"
        f"Expected diff: {json.dumps(task.get('expected_diff', True), ensure_ascii=False)}\n"
        f"Verification policy: {task.get('verification_policy', 'full')}\n"
        f"Read budget profile: {task.get('read_budget_profile', 'quick_triage')}\n"
        f"Read budget: {json.dumps(task.get('read_budget', {}), ensure_ascii=False)}\n"
        "Do not read run artifacts outside the worktree; this prompt is the authoritative task context.\n"
        "World Core will run the listed verification commands after you return; do not spend many turns on full-suite testing.\n"
        "Respect the task mode, expected diff, verification policy, and read budget before exploring more files.\n"
        f"{read_only_completion_rule}"
        f"{required_output}"
        f"{project_memory}"
        f"{profile_strategy}"
        "Return changed_files, summary, test_suggestions, risks, needs_user."
    )
    if task.get("vision_observation"):
        task_section += (
            "\n\n## Vision Observation\n\n"
            "Use this MiMo direct-API observation as visual context. Do not call `claude --file`.\n"
            f"{json.dumps(task['vision_observation'], ensure_ascii=False, indent=2)}\n"
        )
    if worker == "opencode" and _OPENCODE_WORKER_PROMPT_PATH.exists():
        return _OPENCODE_WORKER_PROMPT_PATH.read_text(encoding="utf-8").rstrip() + task_section
    if worker == "claude_code" and _CLAUDE_CODE_WORKER_PROMPT_PATH.exists():
        return _CLAUDE_CODE_WORKER_PROMPT_PATH.read_text(encoding="utf-8").rstrip() + task_section
    return (
        "You are a background coding worker. Do not push, merge, or edit forbidden paths.\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        "Return changed_files, summary, test_suggestions, risks."
    )


def _project_memory_section(task: dict[str, Any]) -> str:
    payload = task.get("project_memory")
    if not isinstance(payload, dict):
        return ""
    prompt = payload.get("prompt")
    return str(prompt) if isinstance(prompt, str) else ""
