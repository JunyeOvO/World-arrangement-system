from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Worker, WorkerResult
from .git_diff import detect_changed_files, export_patch, validate_file_ownership
from ..command_utils import build_command, command_available, subprocess_cwd, subprocess_env
from ..constants import DEFAULT_CLAUDE_CMD
from ..env_profiles import env_for_model, redacted_env_keys
from ..llm_capability import capability_profile, env_for_capability
from ..process_control import run_managed_process


# ── Providers ClaudeCodeWorker is allowed to use (Hotpatch: no GLM) ──
_ALLOWED_PROVIDERS = {"deepseek", "mimo"}
_FORBIDDEN_MODEL_PATTERNS = ["glm", "z_ai", "z.ai", "chatglm"]

# ── Minimal env allowlist for worker subprocess (security: no full os.environ copy) ──
_BASE_ENV_ALLOWLIST = {
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TERM", "TMPDIR",
}

_WORKER_ENV_ALLOWLIST = {
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
    "API_TIMEOUT_MS", "CLAUDE_CODE_EFFORT_LEVEL",
    "AI_ORCHESTRATOR_RUNTIME", "AI_ORCHESTRATOR_WORKER",
    "AI_ORCHESTRATOR_WORKTREE", "AI_ORCHESTRATOR_NO_PUSH",
    "AI_ORCHESTRATOR_NO_MERGE", "AI_ORCHESTRATOR_CAPABILITY_TIER",
    "AI_ORCHESTRATOR_CONTEXT_POLICY", "AI_ORCHESTRATOR_CONTEXT_BUDGET",
    "AI_ORCHESTRATOR_PROMPT_BUDGET",
}

# Explicitly blocked from subprocess env
_BLOCKED_ENV_PATTERNS = [
    "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "CLAUDE_GW_PROXY",
    "OPENAI_", "GITHUB_", "GH_", "NPM_", "HF_", "AWS_",
    "GOOGLE_APPLICATION", "DEEPSEEK_API_KEY", "MIMO_API_KEY",
]


def _build_minimal_worker_env(profile_env: dict) -> dict:
    """Build minimal worker subprocess env.

    Only allowlisted base vars + allowlisted profile vars are passed.
    Explicitly blocks proxy vars unless profile declares them.
    """
    env = {}

    for key in _BASE_ENV_ALLOWLIST:
        if key in os.environ:
            env[key] = os.environ[key]

    for key, value in profile_env.items():
        if key in _WORKER_ENV_ALLOWLIST:
            env[key] = value

    # Block any env var matching sensitive patterns
    for parent_key, parent_value in os.environ.items():
        for pattern in _BLOCKED_ENV_PATTERNS:
            if pattern in parent_key.upper():
                break
        else:
            continue
        # Only log, don't pass through
        pass

    env["AI_ORCHESTRATOR_SANITIZED_ENV"] = "true"
    env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"

    return env


def _inject_path_constraints(
    prompt: str,
    owned_paths: list[str],
    readonly_paths: list[str],
    forbidden_paths: list[str],
) -> str:
    """Inject path ownership constraints into the worker prompt.

    Per World vNext WorkerTask protocol: each worker must respect
    owned_paths (may modify), readonly_paths (may read only),
    and forbidden_paths (must not read or modify).
    """
    section = "\n\n## Path Ownership (WorkerTask Protocol)\n\n"

    if owned_paths:
        section += "### Owned Paths (you may modify)\n"
        for p in owned_paths:
            section += f"- `{p}`\n"
        section += "\n"

    if readonly_paths:
        section += "### Read-only Paths (you may read but NOT modify)\n"
        for p in readonly_paths:
            section += f"- `{p}`\n"
        section += "\n"

    if forbidden_paths:
        section += "### Forbidden Paths (do NOT read or modify)\n"
        for p in forbidden_paths:
            section += f"- `{p}`\n"
        section += "\n"

    section += (
        "**Hard Rule**: You must not modify any file outside your owned paths. "
        "Violating path ownership will cause your patch to be rejected by PatchMerger.\n"
    )

    return prompt.rstrip() + section


def _collect_worktree_patch(
    worktree: Path,
    worker_dir: Path,
    task: dict,
) -> tuple[list[str], str | None, str | None, list[str]]:
    if not worktree.is_dir():
        return [], None, None, []

    changed_files = detect_changed_files(worktree)
    patch_file: str | None = None
    rollback_notes: str | None = None
    if changed_files:
        patch_path = worker_dir / "worker.patch"
        if export_patch(worktree, patch_path):
            patch_file = str(patch_path)
            rollback_notes = f"Reverse patch {patch_path.name}"
        else:
            rollback_notes = "Diff detected but patch export failed"
    else:
        rollback_notes = "No diff to export"

    ownership_violations = validate_file_ownership(
        changed_files,
        task.get("owned_paths", []),
        task.get("forbidden_paths", []),
    )
    return changed_files, patch_file, rollback_notes, ownership_violations


class ClaudeCodeWorker(Worker):
    name = "claude_code"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        selected_model = str(route.get("selected_model") or route.get("model") or "")

        # ── Hotpatch: reject GLM models ──
        if any(p in selected_model.lower() for p in _FORBIDDEN_MODEL_PATTERNS):
            return WorkerResult(
                "blocked",
                f"ClaudeCodeWorker does not accept GLM models: {selected_model}. GLM-5.2 must use OpenCodeWorker.",
                [], task.get("test_commands", []),
                [f"forbidden_model={selected_model}", "action=route_to_opencode_worker"],
                True, "", "",
            )

        claude_cmd = os.environ.get("AI_CLAUDE_CMD", DEFAULT_CLAUDE_CMD)
        profile_env, profile_path = env_for_model(selected_model)
        llm_profile = route.get("capability_profile") or capability_profile(
            selected_model,
            route.get("capability_tier"),
            route.get("intensity"),
        )
        profile_env = {**profile_env, **env_for_capability(llm_profile)}
        worker_dir = Path(task["run_dir"]) / "worker"
        worker_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = worker_dir / "worker.stream.jsonl"
        stderr_path = worker_dir / "stderr.log"
        # ── Path ownership constraints (vNext WorkerTask protocol) ──
        owned_paths = task.get("owned_paths", [])
        readonly_paths = task.get("readonly_paths", [])
        forbidden_paths = task.get("forbidden_paths", [])
        if owned_paths or readonly_paths or forbidden_paths:
            prompt = _inject_path_constraints(prompt, owned_paths, readonly_paths, forbidden_paths)
        (worker_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        available, _ = command_available(claude_cmd)
        if dry_run or not available:
            stdout_path.write_text(json.dumps({"event": "mock", "worker": self.name}) + "\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return WorkerResult(
                "success",
                "mock Claude Code worker completed without editing files",
                [],
                task.get("test_commands", []),
                [
                    f"dry-run or Claude Code CLI unavailable: {claude_cmd}",
                    f"env_profile={profile_path}",
                    f"capability_tier={llm_profile.get('tier')}",
                    f"context_policy={llm_profile.get('context_policy')}",
                    f"env_keys={redacted_env_keys(profile_env)}",
                ],
                False,
                str(stdout_path),
                str(stderr_path),
            )
        cmd = build_command(
            claude_cmd,
            [
                "-p",
                "--model",
                profile_env.get("ANTHROPIC_MODEL", selected_model),
                "--output-format",
                "stream-json",
                "--verbose",
                "--max-turns",
                str(int(route.get("max_turns", 20))),
                "--no-session-persistence",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools=Read,Edit,Bash",
                prompt,
            ],
            profile_env,
            cwd=worktree,
        )
        child_env = _build_minimal_worker_env(profile_env)
        timeout_sec = int(route.get("timeout_sec", 2700))
        proc = run_managed_process(
            cmd,
            cwd=subprocess_cwd(claude_cmd, worktree),
            env=subprocess_env(claude_cmd, child_env),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            run_dir=Path(task["run_dir"]),
            task_id=str(task.get("task_id", "")),
            label=self.name,
            timeout_sec=timeout_sec,
        )
        if proc.cancelled:
            return WorkerResult(
                "cancelled",
                "Claude Code worker cancelled",
                [],
                task.get("test_commands", []),
                ["worker_cancelled", f"env_profile={profile_path}"],
                False,
                str(stdout_path),
                str(stderr_path),
            )
        if proc.timed_out:
            return WorkerResult(
                "failed",
                "Claude Code worker timed out",
                [],
                task.get("test_commands", []),
                [f"command_timeout after {timeout_sec}s", f"env_profile={profile_path}"],
                False,
                str(stdout_path),
                str(stderr_path),
            )
        success = proc.returncode == 0
        changed_files, patch_file, rollback_notes, ownership_violations = _collect_worktree_patch(
            worktree,
            worker_dir,
            task,
        )
        risks = (
            [f"env_profile={profile_path}", f"env_keys={redacted_env_keys(profile_env)}"]
            if success
            else [
                proc.stderr_tail[-500:],
                f"env_profile={profile_path}",
                f"worker_returncode={proc.returncode}",
            ]
        )
        if patch_file and not success:
            risks.append("diff_exported_after_worker_failure")
        if ownership_violations:
            risks.extend(ownership_violations)
        return WorkerResult(
            "success" if success else "failed",
            "Claude Code worker finished" if success else "Claude Code worker failed with exported diff" if patch_file else "Claude Code worker failed",
            changed_files,
            task.get("test_commands", []),
            risks,
            False,
            str(stdout_path),
            str(stderr_path),
            patch_file=patch_file,
            tests_run=[],
            rollback_notes=rollback_notes,
        )
