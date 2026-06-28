from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path


def command_tokens(value: str) -> list[str]:
    return shlex.split(value, posix=False)


def command_available(value: str) -> tuple[bool, str]:
    tokens = command_tokens(value)
    if not tokens:
        return False, "empty command"
    executable = tokens[0]
    path = shutil.which(executable)
    if not path:
        return False, f"{executable} missing"
    if executable.lower() == "wsl":
        return _wsl_command_available(tokens, path)
    return True, f"{value} -> {path}"


def build_command(
    value: str,
    args: list[str],
    env_overrides: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> list[str]:
    tokens = command_tokens(value)
    env_overrides = env_overrides or {}
    if not tokens:
        raise ValueError("empty command")
    if tokens[0].lower() == "wsl":
        return _build_wsl_command(tokens, args, env_overrides, cwd)
    return [*tokens, *args]


def command_runs_in_wsl(value: str) -> bool:
    tokens = command_tokens(value)
    return bool(tokens) and tokens[0].lower() == "wsl"


def subprocess_cwd(value: str, cwd: str | Path) -> str | Path | None:
    return None if command_runs_in_wsl(value) else cwd


def subprocess_env(value: str, env: dict[str, str]) -> dict[str, str] | None:
    return None if command_runs_in_wsl(value) else env


def path_for_wsl(path: str | Path) -> str:
    p = Path(path)
    drive = p.drive.rstrip(":").lower()
    if drive and len(drive) == 1:
        rest = p.relative_to(p.anchor).as_posix()
        return f"/mnt/{drive}/{rest}"
    return str(path).replace("\\", "/")


def _build_wsl_command(
    tokens: list[str],
    args: list[str],
    env_overrides: dict[str, str],
    cwd: str | Path | None,
) -> list[str]:
    inner = _wsl_inner_command(tokens)
    if not inner:
        return [*tokens, *args]

    env_parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(env_overrides.items())]
    shell_parts = []
    if env_parts:
        shell_parts.extend(["env", *env_parts])
    shell_parts.extend([shlex.quote(inner), *[shlex.quote(str(arg)) for arg in args]])
    shell_command = " ".join(shell_parts)
    if cwd is not None:
        shell_command = f"cd {shlex.quote(path_for_wsl(cwd))} && {shell_command}"

    for flag in ("-e", "--exec"):
        if flag in tokens:
            idx = tokens.index(flag)
            return [*tokens[: idx + 1], "sh", "-lc", shell_command]
    return [*tokens, "-e", "sh", "-lc", shell_command]


def _wsl_command_available(tokens: list[str], wsl_path: str) -> tuple[bool, str]:
    inner = _wsl_inner_command(tokens)
    if not inner:
        return True, f"{' '.join(tokens)} -> {wsl_path}"
    try:
        proc = subprocess.run(
            ["wsl", "-e", "sh", "-lc", f"command -v {shlex.quote(inner)}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"wsl command check failed for {inner}: {exc}"
    if proc.returncode == 0 and proc.stdout.strip():
        return True, f"{' '.join(tokens)} -> {wsl_path}; WSL:{inner} -> {proc.stdout.strip()}"
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, f"{' '.join(tokens)} -> {wsl_path}; WSL:{inner} missing" + (f": {detail}" if detail else "")


def _wsl_inner_command(tokens: list[str]) -> str | None:
    for flag in ("-e", "--exec"):
        if flag in tokens:
            idx = tokens.index(flag)
            if idx + 1 < len(tokens):
                return tokens[idx + 1]
    if len(tokens) > 1:
        return tokens[-1]
    return None
