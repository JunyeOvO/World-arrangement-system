from orchestrator.command_utils import build_command, path_for_wsl, subprocess_cwd, subprocess_env
from orchestrator.constants import DEFAULT_CLAUDE_CMD, DEFAULT_OPENCODE_CMD


def test_build_plain_command():
    assert build_command("claude", ["-p", "hello"], {"A": "B"}) == ["claude", "-p", "hello"]


def test_build_wsl_command_injects_env():
    cmd = build_command("wsl -e claude", ["-p", "hello"], {"ANTHROPIC_BASE_URL": "https://x"})
    assert cmd[:4] == ["wsl", "-e", "sh", "-lc"]
    assert "env ANTHROPIC_BASE_URL=https://x claude -p hello" == cmd[4]


def test_build_wsl_command_changes_directory_inside_wsl():
    cmd = build_command("wsl -e claude", ["-p", "hello"], {}, cwd=r"C:\tmp\repo")
    assert cmd[:4] == ["wsl", "-e", "sh", "-lc"]
    assert cmd[4] == "cd /mnt/c/tmp/repo && claude -p hello"
    assert subprocess_cwd("wsl -e claude", r"C:\tmp\repo") is None
    assert subprocess_env("wsl -e claude", {"PATH": "x"}) == {"PATH": "x"}


def test_wsl_subprocess_env_uses_sanitized_env_not_parent_inheritance():
    env = {"PATH": "safe", "AI_ORCHESTRATOR_SANITIZED_ENV": "true"}

    assert subprocess_env("wsl -e claude", env) is env


def test_path_for_wsl_converts_windows_drive_path():
    assert path_for_wsl(r"C:\Users\fujunye\repo") == "/mnt/c/Users/fujunye/repo"


def test_default_worker_commands_are_wsl_only():
    assert DEFAULT_CLAUDE_CMD.startswith("wsl -e ")
    assert DEFAULT_OPENCODE_CMD.startswith("wsl -e ")
