from __future__ import annotations

import json
import sys

from orchestrator.process_control import (
    _merge_finished_process_payload,
    redact_command,
    request_cancel,
    run_managed_process,
)


def test_run_managed_process_times_out_and_writes_control_files(tmp_path):
    result = run_managed_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env=None,
        stdout_path=tmp_path / "worker" / "stdout.log",
        stderr_path=tmp_path / "worker" / "stderr.log",
        run_dir=tmp_path,
        task_id="t_timeout",
        label="test_worker",
        timeout_sec=1,
    )

    process = json.loads((tmp_path / "control" / "process.json").read_text(encoding="utf-8"))
    heartbeat = json.loads((tmp_path / "control" / "heartbeat.json").read_text(encoding="utf-8"))

    assert result.timed_out is True
    assert result.status == "timed_out"
    assert process["status"] == "timed_out"
    assert process["timed_out"] is True
    assert process["pid"] > 0
    assert process["process_token"]
    assert heartbeat["status"] == "timed_out"
    assert heartbeat["process_token"] == process["process_token"]
    assert "stream_closed" in (tmp_path / "worker" / "stdout.log").read_text(encoding="utf-8")
    assert not (tmp_path / "control" / "process.json.lock").exists()
    assert not (tmp_path / "control" / "heartbeat.json.lock").exists()


def test_request_cancel_writes_cancel_file_and_marks_process(monkeypatch, tmp_path):
    calls = []

    def fake_terminate(pid):
        calls.append(pid)
        return {"pid": pid, "attempted": True, "method": "fake", "returncode": 0}

    monkeypatch.setattr("orchestrator.process_control.terminate_process_tree", fake_terminate)
    control = tmp_path / "control"
    control.mkdir()
    (control / "process.json").write_text(
        json.dumps({"pid": 12345, "status": "running", "process_token": "token-1"}), encoding="utf-8"
    )

    result = request_cancel(tmp_path, "stop requested")
    process = json.loads((control / "process.json").read_text(encoding="utf-8"))
    cancel = json.loads((control / "cancel.requested").read_text(encoding="utf-8"))

    assert calls == [12345]
    assert result["pid"] == 12345
    assert result["process_token"] == "token-1"
    assert cancel["reason"] == "stop requested"
    assert process["status"] == "cancelled"
    assert process["cancel_reason"] == "stop requested"


def test_redact_command_omits_wsl_shell_and_secrets():
    assert redact_command(["wsl", "-e", "sh", "-lc", "env API_KEY=sk-secret opencode run prompt"]) == [
        "wsl",
        "-e",
        "sh",
        "-lc",
        "[shell-command-omitted]",
    ]
    assert "[redacted]" in redact_command(["tool", "--token", "sk-secret"])


def test_finished_process_merge_preserves_concurrent_cancelled_state():
    payload = _merge_finished_process_payload(
        {"pid": 123, "status": "cancelled", "cancel_reason": "user stop"},
        status="succeeded",
        returncode=0,
        elapsed_sec=1.2,
        timed_out=False,
        cancelled=False,
        killed=None,
    )

    assert payload["status"] == "cancelled"
    assert payload["cancelled"] is True
    assert payload["timed_out"] is False
    assert payload["cancel_reason"] == "user stop"
