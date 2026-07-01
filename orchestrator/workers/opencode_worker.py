from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from .base import Worker, WorkerResult
from .git_diff import detect_changed_files, export_patch, validate_file_ownership
from .claude_code_worker import _build_minimal_worker_env
from ..command_utils import build_command, command_available, subprocess_cwd, subprocess_env
from ..constants import DEFAULT_OPENCODE_CMD
from ..env_profiles import model_spec
from ..llm_capability import capability_profile
from ..permissions import check_worker_launch_command
from ..process_control import run_managed_process


# opencode CLI only accepts these --variant values.
# Spec "default" maps to "omit the flag" (save quota / conservative).
_VALID_CLI_VARIANTS = {"high", "max", "minimal"}


def _normalize_variant(value: str | None) -> tuple[str | None, str | None]:
    """Normalize a variant value to a CLI-acceptable form.

    Returns (cli_variant_or_None, warning_or_None). ``None`` cli_variant means
    the ``--variant`` flag must be omitted. Unknown values are downgraded to
    "omit" with a warning instead of being passed to the CLI.
    """
    if value is None or str(value).strip() == "" or str(value).strip().lower() == "default":
        return None, None
    v = str(value).strip().lower()
    if v in _VALID_CLI_VARIANTS:
        return v, None
    return None, f"unknown variant '{value}' downgraded to omit (valid: high|max|minimal)"


def assert_valid_opencode_args(args: list[str]) -> None:
    """Post-construction guard: --variant may only ever be high|max|minimal.

    Catches bugs where someone bypasses _normalize_variant and inserts an
    illegal value (e.g. ``--variant default``) into the CLI args. Raises
    ValueError on violation so the worker fails fast instead of sending a
    bad flag to the opencode CLI.
    """
    for i, arg in enumerate(args):
        if arg == "--variant":
            if i + 1 >= len(args):
                raise ValueError("--variant flag is missing its value")
            value = args[i + 1]
            if value not in _VALID_CLI_VARIANTS:
                raise ValueError(
                    f"Invalid OpenCode --variant value: {value!r} (legal: high|max|minimal)"
                )


def _path_for_cli(path: Path, command_value: str) -> str:
    """Convert Windows paths for CLIs that execute inside WSL."""
    text = str(path)
    if not command_value.lower().startswith("wsl"):
        return text
    drive = path.drive.rstrip(":").lower()
    if drive and len(drive) == 1:
        rest = path.relative_to(path.anchor).as_posix()
        return f"/mnt/{drive}/{rest}"
    return text.replace("\\", "/")


class OpenCodeWorker(Worker):
    name = "opencode"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        opencode_cmd = os.environ.get("AI_OPENCODE_CMD", DEFAULT_OPENCODE_CMD)
        selected_model = str(route.get("selected_model") or route.get("model") or "")
        spec = model_spec(selected_model)
        llm_profile = route.get("capability_profile") or capability_profile(
            selected_model,
            route.get("capability_tier"),
            route.get("intensity"),
        )
        cli_model = spec.get("model", selected_model or "opencode-go/glm-5.2")
        worker_dir = Path(task["run_dir"]) / "worker"
        worker_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = worker_dir / "worker.stdout.jsonl"
        stderr_path = worker_dir / "stderr.log"
        (worker_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        available, _ = command_available(opencode_cmd)
        if dry_run or not available:
            stdout_path.write_text(json.dumps({"event": "mock", "worker": self.name}) + "\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            reason = "dry-run requested" if dry_run else f"OpenCode CLI unavailable: {opencode_cmd}"
            return WorkerResult(
                "success",
                "DEGRADED_MOCK_RESULT: OpenCode worker did not run real analysis or edits",
                [],
                task.get("test_commands", []),
                [
                    reason,
                    "api_route=opencode_cli_direct",
                    f"capability_tier={llm_profile.get('tier')}",
                    f"context_policy={llm_profile.get('context_policy')}",
                ],
                False,
                str(stdout_path),
                str(stderr_path),
                patch_file=None,
                tests_run=[],
                rollback_notes="dry_run: no changes to rollback",
                degraded=True,
                degradation_reason=reason,
                mock_result=True,
            )
        task_id = str(task.get("task_id", ""))
        args = [
            "run",
            "-m",
            cli_model,
            "--format",
            "json",
            "--dir",
            _path_for_cli(worktree, opencode_cmd),
            "--title",
            task_id,
            prompt,
        ]
        variant_raw = route.get("variant")
        if variant_raw is None:
            variant_raw = llm_profile.get("variant")
        if variant_raw is None:
            variant_raw = spec.get("default_variant")
        cli_variant, variant_warning = _normalize_variant(variant_raw)
        if cli_variant:
            args[1:1] = ["--variant", cli_variant]
        cmd = build_command(opencode_cmd, args, {}, cwd=worktree)
        # Validate launcher and fixed CLI args only. The user/system prompt is a
        # data argument and may legitimately mention denied flags while asking
        # the worker to avoid them; scanning it would create false BLOCKED tasks.
        launch_check_args = [*args[:-1], "<prompt>"]
        launch_check_cmd = build_command(opencode_cmd, launch_check_args, {}, cwd=worktree)
        # A4: post-construction guard — never allow --variant with an illegal value
        # (e.g. "default") to reach the opencode CLI. Bypasses of _normalize_variant
        # trip this and fail the worker fast with a clear error.
        assert_valid_opencode_args(launch_check_cmd)
        command_check = check_worker_launch_command(
            self.name,
            shlex.join(str(part) for part in launch_check_cmd),
        )
        if not command_check.allowed:
            return WorkerResult(
                "blocked",
                "OpenCode worker command denied by static permissions",
                [],
                task.get("test_commands", []),
                [command_check.reason, "api_route=opencode_cli_direct"],
                True,
                str(stdout_path),
                str(stderr_path),
                patch_file=None,
                tests_run=[],
                rollback_notes=None,
            )
        timeout_sec = int(route.get("timeout_sec", 2700))
        child_env = _build_minimal_worker_env(os.environ.copy())
        proc = run_managed_process(
            cmd,
            cwd=subprocess_cwd(opencode_cmd, worktree),
            env=subprocess_env(opencode_cmd, child_env),
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
                "OpenCode worker cancelled",
                [],
                task.get("test_commands", []),
                ["worker_cancelled", "api_route=opencode_cli_direct"],
                False,
                str(stdout_path),
                str(stderr_path),
                patch_file=None,
                tests_run=[],
                rollback_notes=None,
            )
        if proc.timed_out:
            return WorkerResult(
                "failed",
                "OpenCode worker timed out",
                [],
                task.get("test_commands", []),
                [f"command_timeout after {timeout_sec}s", "api_route=opencode_cli_direct"],
                False,
                str(stdout_path),
                str(stderr_path),
                patch_file=None,
                tests_run=[],
                rollback_notes=None,
            )
        success = proc.returncode == 0

        changed_files: list[str] = []
        patch_file: str | None = None
        rollback_notes: str | None = None
        ownership_violations: list[str] = []

        if success and worktree.is_dir():
            changed_files = detect_changed_files(worktree)
            patch_path = worker_dir / "worker.patch"
            if export_patch(worktree, patch_path):
                patch_file = str(patch_path)
                rollback_notes = f"Reverse patch {patch_path.name}"
            else:
                rollback_notes = "No diff to export"
            owned_paths = task.get("owned_paths", [])
            forbidden_paths = task.get("forbidden_paths", [])
            ownership_violations = validate_file_ownership(changed_files, owned_paths, forbidden_paths)

        risks = (["api_route=opencode_cli_direct"]
                 if success
                 else [proc.stderr_tail[-500:], "api_route=opencode_cli_direct"])
        if variant_warning:
            risks.insert(0, variant_warning)
        if ownership_violations:
            risks.extend(ownership_violations)

        summary = _extract_opencode_summary(stdout_path)

        return WorkerResult(
            "success" if success else "failed",
            summary or ("OpenCode worker finished" if success else "OpenCode worker failed"),
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


def _extract_opencode_summary(path: Path) -> str | None:
    """Extract the final assistant text from OpenCode JSONL output.

    OpenCode emits text as top-level ``{"type":"text","part":{"text":...}}``
    events. Older scheduler recovery code only understood Claude-style result
    events, so completed OpenCode tasks lost their real report in result.json.
    """
    if not path.exists():
        return None
    latest_text: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        text = _event_text(event)
        if text:
            latest_text = text
    return latest_text


def _event_text(event: dict) -> str | None:
    part = event.get("part")
    if event.get("type") == "text" and isinstance(part, dict):
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ).strip()
            if text:
                return text
    return None
