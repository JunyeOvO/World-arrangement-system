"""Hotpatch-required worker tests."""
import json
from pathlib import Path

from orchestrator.process_control import ManagedProcessResult
from orchestrator.workers.claude_code_worker import ClaudeCodeWorker
from orchestrator.workers.git_diff import detect_changed_files, export_patch
from orchestrator.workers.opencode_worker import OpenCodeWorker


def _dummy_route(model: str = "deepseek_pro", worker: str = "claude_code") -> dict:
    return {"selected_model": model, "selected_worker": worker, "variant": "high"}


def _dummy_task() -> dict:
    return {"run_dir": ".", "task_id": "t_test", "test_commands": [], "build_commands": []}


def test_claude_code_worker_forbids_glm():
    """Hotpatch: ClaudeCodeWorker must reject GLM models."""
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        _dummy_route(model="glm_advanced", worker="claude_code"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "blocked"
    assert "GLM" in result.summary


def test_claude_code_worker_forbids_glm_routine():
    """Hotpatch: ClaudeCodeWorker must reject glm_routine."""
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        _dummy_route(model="glm_routine", worker="claude_code"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "blocked"


def test_claude_code_worker_accepts_deepseek():
    """Hotpatch: ClaudeCodeWorker must accept deepseek_pro."""
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        _dummy_route(model="deepseek_pro", worker="claude_code"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "success"  # dry-run mock success


def test_claude_worker_accepts_retry_attempt_model_key():
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        {"model": "deepseek_flash", "worker": "claude_code"},
        _dummy_task(), dry_run=True,
    )

    assert result.status == "success"
    assert any("deepseek_flash.env" in risk for risk in result.risks)


def test_claude_code_worker_accepts_mimo_v25():
    """Hotpatch: ClaudeCodeWorker must accept MiMo V2.5."""
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        _dummy_route(model="mimo_v25", worker="claude_code"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "success"


def test_claude_code_worker_accepts_mimo_v25_pro():
    """Hotpatch: ClaudeCodeWorker must accept MiMo V2.5 Pro."""
    worker = ClaudeCodeWorker()
    result = worker.run(
        "do something", Path("."),
        _dummy_route(model="mimo_v25_pro", worker="claude_code"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "success"


def test_opencode_worker_dry_run():
    """Hotpatch: OpenCodeWorker dry-run should return mock success."""
    worker = OpenCodeWorker()
    result = worker.run(
        "use GLM-5.2 to fix code", Path("."),
        _dummy_route(model="opencode-go/glm-5.2", worker="opencode"),
        _dummy_task(), dry_run=True,
    )
    assert result.status == "success"


def test_opencode_worker_accepts_retry_attempt_model_key(tmp_path):
    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_attempt", "test_commands": [], "build_commands": []}
    result = worker.run(
        "use GLM-5.2 to fix code",
        tmp_path,
        {"model": "opencode-go/glm-5.2", "worker": "opencode"},
        task,
        dry_run=True,
    )

    assert result.status == "success"
    assert "api_route=opencode_cli_direct" in result.risks


def test_claude_worker_timeout_returns_failure(monkeypatch, tmp_path):
    def _timeout(*args, **kwargs):
        return ManagedProcessResult(
            returncode=None,
            stdout_path=str(tmp_path / "worker" / "worker.stream.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            timed_out=True,
            status="timed_out",
        )

    monkeypatch.setattr("orchestrator.workers.claude_code_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.run_managed_process", _timeout)

    worker = ClaudeCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_timeout", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "deepseek_flash", "timeout_sec": 1}, task)

    assert result.status == "failed"
    assert "timed out" in result.summary
    assert any("command_timeout" in risk for risk in result.risks)


def test_claude_worker_failed_process_exports_existing_diff(monkeypatch, tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)
    target = tmp_path / "app.py"
    target.write_text("print('before')\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    target.write_text("print('after')\n", encoding="utf-8")

    def _failed(*args, **kwargs):
        return ManagedProcessResult(
            returncode=1,
            stdout_path=str(tmp_path / "worker" / "worker.stream.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            stderr_tail="Reached maximum number of turns",
            status="failed",
        )

    monkeypatch.setattr("orchestrator.workers.claude_code_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.run_managed_process", _failed)

    worker = ClaudeCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_max_turns", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "deepseek_flash"}, task)

    assert result.status == "failed"
    assert result.changed_files == ["app.py"]
    assert result.patch_file is not None
    assert Path(result.patch_file).exists()
    assert "after" in Path(result.patch_file).read_text(encoding="utf-8")
    assert "diff_exported_after_worker_failure" in result.risks


def test_claude_worker_uses_route_max_turns(monkeypatch, tmp_path):
    observed = {}

    def _build_command(value, args, env_overrides=None, cwd=None):
        observed["args"] = list(args)
        return ["claude", *args]

    def _success(*args, **kwargs):
        return ManagedProcessResult(
            returncode=0,
            stdout_path=str(tmp_path / "worker" / "worker.stream.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            status="succeeded",
        )

    monkeypatch.setattr("orchestrator.workers.claude_code_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.build_command", _build_command)
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.run_managed_process", _success)

    worker = ClaudeCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_turns", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "deepseek_flash", "max_turns": 24}, task)

    assert result.status == "success"
    idx = observed["args"].index("--max-turns")
    assert observed["args"][idx + 1] == "24"


def test_claude_worker_summary_uses_stream_result_and_ignores_prompt_for_launch_permissions(monkeypatch, tmp_path):
    expected = "Travel With Me quality: solid architecture, good tests, remaining visual QA risk."

    def _build_command(value, args, env_overrides=None, cwd=None):
        return ["claude", *args]

    def _success(cmd, **kwargs):
        stdout_path = Path(kwargs["stdout_path"])
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(
            json.dumps({"type": "result", "subtype": "success", "result": expected}) + "\n",
            encoding="utf-8",
        )
        return ManagedProcessResult(
            returncode=0,
            stdout_path=str(stdout_path),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            status="succeeded",
        )

    monkeypatch.setenv("AI_CLAUDE_CMD", "claude")
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.build_command", _build_command)
    monkeypatch.setattr("orchestrator.workers.claude_code_worker.run_managed_process", _success)

    worker = ClaudeCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_summary", "test_commands": [], "build_commands": []}
    result = worker.run(
        "Review text mentioning --dangerously-skip-permissions, but do not use it.",
        tmp_path,
        {"selected_model": "deepseek_flash"},
        task,
    )

    assert result.status == "success"
    assert result.summary == expected


def test_opencode_worker_timeout_returns_failure(monkeypatch, tmp_path):
    def _timeout(*args, **kwargs):
        return ManagedProcessResult(
            returncode=None,
            stdout_path=str(tmp_path / "worker" / "worker.stdout.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            timed_out=True,
            status="timed_out",
        )

    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _timeout)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_timeout", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "opencode-go/glm-5.2", "timeout_sec": 1}, task)

    assert result.status == "failed"
    assert "timed out" in result.summary
    assert any("command_timeout" in risk for risk in result.risks)


def test_opencode_worker_cancelled_returns_cancelled(monkeypatch, tmp_path):
    def _cancelled(*args, **kwargs):
        return ManagedProcessResult(
            returncode=None,
            stdout_path=str(tmp_path / "worker" / "worker.stdout.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            cancelled=True,
            status="cancelled",
        )

    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _cancelled)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_cancel", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "opencode-go/glm-5.2", "timeout_sec": 1}, task)

    assert result.status == "cancelled"
    assert "cancelled" in result.summary
    assert "worker_cancelled" in result.risks


def test_opencode_worker_does_not_inject_provider_env(monkeypatch, tmp_path):
    observed = {}

    def _build_command(value, args, env_overrides=None, cwd=None):
        observed["env_overrides"] = dict(env_overrides or {})
        observed["args"] = list(args)
        return ["opencode", *args]

    def _success(*args, **kwargs):
        observed["subprocess_env"] = kwargs.get("env")
        return ManagedProcessResult(
            returncode=0,
            stdout_path=str(tmp_path / "worker" / "worker.stdout.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            status="succeeded",
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-in-command")
    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.build_command", _build_command)
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _success)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_direct", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "opencode-go/glm-5.2"}, task)

    assert result.status == "success"
    assert observed["env_overrides"] == {}
    assert "-m" in observed["args"]
    assert "api_route=opencode_cli_direct" in result.risks


def test_opencode_worker_blocks_denied_launch_command(monkeypatch, tmp_path):
    called = {"run": False}

    def _build_command(value, args, env_overrides=None, cwd=None):
        return ["opencode", "run", "--dangerously-skip-permissions"]

    def _run(*args, **kwargs):
        called["run"] = True
        raise AssertionError("denied worker command should not execute")

    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.build_command", _build_command)
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _run)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_denied", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "opencode-go/glm-5.2"}, task)

    assert result.status == "blocked"
    assert called["run"] is False
    assert any("dangerously-skip-permissions" in risk for risk in result.risks)


def test_opencode_worker_does_not_scan_prompt_for_launch_permissions(monkeypatch, tmp_path):
    called = {"run": False}

    def _success(*args, **kwargs):
        called["run"] = True
        return ManagedProcessResult(
            returncode=0,
            stdout_path=str(tmp_path / "worker" / "worker.stdout.jsonl"),
            stderr_path=str(tmp_path / "worker" / "stderr.log"),
            status="succeeded",
        )

    monkeypatch.setenv("AI_OPENCODE_CMD", "opencode")
    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _success)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_prompt_text", "test_commands": [], "build_commands": []}
    result = worker.run(
        "Review the policy text mentioning --dangerously-skip-permissions, but do not use that flag.",
        tmp_path,
        {"selected_model": "opencode-go/glm-5.2"},
        task,
    )

    assert result.status == "success"
    assert called["run"] is True


def test_opencode_worker_still_blocks_denied_launcher_env(monkeypatch, tmp_path):
    called = {"run": False}

    def _run(*args, **kwargs):
        called["run"] = True
        raise AssertionError("denied launcher command should not execute")

    monkeypatch.setenv("AI_OPENCODE_CMD", "opencode --dangerously-skip-permissions")
    monkeypatch.setattr("orchestrator.workers.opencode_worker.command_available", lambda cmd: (True, cmd))
    monkeypatch.setattr("orchestrator.workers.opencode_worker.run_managed_process", _run)

    worker = OpenCodeWorker()
    task = {"run_dir": str(tmp_path), "task_id": "t_denied_env", "test_commands": [], "build_commands": []}
    result = worker.run("prompt", tmp_path, {"selected_model": "opencode-go/glm-5.2"}, task)

    assert result.status == "blocked"
    assert called["run"] is False
    assert any("dangerously-skip-permissions" in risk for risk in result.risks)


def test_opencode_diff_export_handles_non_ascii(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)
    target = tmp_path / "README.md"
    target.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    target.write_text("hello\n修复\n", encoding="utf-8")

    patch_path = tmp_path / "worker" / "worker.patch"

    assert detect_changed_files(tmp_path) == ["README.md"]
    assert export_patch(tmp_path, patch_path) is True
    assert "修复" in patch_path.read_text(encoding="utf-8")


def test_opencode_worker_forbids_dangerous_skip_permissions():
    """Hotpatch: OpenCodeWorker must never use --dangerously-skip-permissions."""
    from orchestrator.constants import FORBIDDEN_ACTION_PATTERNS
    assert "--dangerously-skip-permissions" in FORBIDDEN_ACTION_PATTERNS
    # Verify the worker doesn't pass the flag (command construction is checked in dry_run)
    worker = OpenCodeWorker()
    result = worker.run(
        "test", Path("."),
        _dummy_route(model="opencode-go/glm-5.2", worker="opencode"),
        _dummy_task(), dry_run=True,
    )
    # Dry-run path never builds the real command, but the risk_policy layer blocks it
    from orchestrator.risk_policy import scan_command
    cmd_result = scan_command("opencode run --dangerously-skip-permissions -m opencode-go/glm-5.2 test")
    assert not cmd_result.allowed


def test_workers_no_hermes():
    """Hotpatch: only Claude Code and OpenCode execution workers should exist."""
    from orchestrator.scheduler import WORKERS
    for wname in WORKERS:
        assert "hermes" not in wname.lower()
    assert set(WORKERS) == {"claude_code", "opencode"}
