from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .control_files import update_json_file, write_json_file


POLL_INTERVAL_SEC = 1.0


@dataclass
class ManagedProcessResult:
    returncode: int | None
    stdout_path: str
    stderr_path: str
    timed_out: bool = False
    cancelled: bool = False
    status: str = "unknown"
    elapsed_sec: float = 0.0
    stdout_tail: str = ""
    stderr_tail: str = ""


def run_managed_process(
    cmd: list[str],
    *,
    cwd: str | Path | None,
    env: dict[str, str] | None,
    stdout_path: Path,
    stderr_path: Path,
    run_dir: Path,
    task_id: str,
    label: str,
    timeout_sec: int,
) -> ManagedProcessResult:
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    cancel_path = control_dir / "cancel.requested"
    process_path = control_dir / "process.json"
    heartbeat_path = control_dir / "heartbeat.json"
    process_token = uuid.uuid4().hex

    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as stderr_file:
        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd is not None else None,
            "env": env,
            "stdout": stdout_file,
            "stderr": stderr_file,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **popen_kwargs)
        _write_json(
            process_path,
            _process_payload(
                task_id=task_id,
                label=label,
                pid=proc.pid,
                status="running",
                started_at=_utc_now(),
                timeout_sec=timeout_sec,
                command=redact_command(cmd),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                process_token=process_token,
            ),
        )

        status = "running"
        timed_out = False
        cancelled = False
        killed = None

        while proc.poll() is None:
            elapsed = time.monotonic() - started
            _write_json(
                heartbeat_path,
                {
                    "task_id": task_id,
                    "label": label,
                    "pid": proc.pid,
                    "process_token": process_token,
                    "status": status,
                    "last_seen": _utc_now(),
                    "elapsed_sec": round(elapsed, 3),
                },
            )
            if cancel_path.exists():
                status = "cancelled"
                cancelled = True
                killed = terminate_process_tree(proc.pid)
                break
            if elapsed >= timeout_sec:
                status = "timed_out"
                timed_out = True
                killed = terminate_process_tree(proc.pid)
                break
            time.sleep(POLL_INTERVAL_SEC)

        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            killed = terminate_process_tree(proc.pid)
            returncode = proc.wait(timeout=10)

    elapsed = time.monotonic() - started
    if cancel_path.exists():
        cancelled = True
        status = "cancelled"
    elif timed_out:
        status = "timed_out"
    elif returncode == 0:
        status = "succeeded"
    else:
        status = "failed"

    def _finish_process(payload: dict[str, Any]) -> dict[str, Any]:
        payload.update(
            {
                "status": status,
                "returncode": returncode,
                "finished_at": _utc_now(),
                "elapsed_sec": round(elapsed, 3),
                "timed_out": timed_out,
                "cancelled": cancelled,
            }
        )
        if killed is not None:
            payload["termination"] = killed
        return payload

    payload = update_json_file(process_path, _finish_process)
    _write_json(
        heartbeat_path,
        {
            "task_id": task_id,
            "label": label,
            "pid": payload.get("pid"),
            "process_token": payload.get("process_token"),
            "status": status,
            "last_seen": _utc_now(),
            "elapsed_sec": round(elapsed, 3),
        },
    )
    _append_stream_sentinel(stdout_path, status=status, returncode=returncode, elapsed_sec=round(elapsed, 3))

    return ManagedProcessResult(
        returncode=returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        timed_out=timed_out,
        cancelled=cancelled,
        status=status,
        elapsed_sec=round(elapsed, 3),
        stdout_tail=_tail_text(stdout_path),
        stderr_tail=_tail_text(stderr_path),
    )


def request_cancel(run_dir: Path, reason: str = "") -> dict[str, Any]:
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    cancel_path = control_dir / "cancel.requested"
    cancel_payload = {
        "requested_at": _utc_now(),
        "reason": reason,
    }
    _write_json(cancel_path, cancel_payload)

    process_path = control_dir / "process.json"
    termination = None

    def _cancel_process(process: dict[str, Any]) -> dict[str, Any]:
        nonlocal termination
        pid = process.get("pid")
        if isinstance(pid, int) and process.get("status") in {None, "running"}:
            termination = terminate_process_tree(pid)
            process.update(
                {
                    "status": "cancelled",
                    "cancelled_at": _utc_now(),
                    "cancel_reason": reason,
                    "termination": termination,
                }
            )
        return process

    process = update_json_file(process_path, _cancel_process)
    pid = process.get("pid")

    return {
        "run_dir": str(run_dir),
        "cancel_file": str(cancel_path),
        "pid": pid,
        "process_token": process.get("process_token"),
        "termination": termination,
    }


def terminate_process_tree(pid: int) -> dict[str, Any]:
    if pid <= 0:
        return {"pid": pid, "attempted": False, "error": "invalid pid"}

    if os.name == "nt":
        proc = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        return {
            "pid": pid,
            "attempted": True,
            "method": "taskkill",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }

    try:
        os.killpg(pid, signal.SIGTERM)
        time.sleep(2)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return {"pid": pid, "attempted": True, "method": "killpg", "returncode": 0}
    except ProcessLookupError:
        return {"pid": pid, "attempted": True, "method": "killpg", "returncode": 0}
    except OSError as exc:
        try:
            os.kill(pid, signal.SIGTERM)
            return {"pid": pid, "attempted": True, "method": "kill", "returncode": 0}
        except OSError as fallback_exc:
            return {
                "pid": pid,
                "attempted": True,
                "method": "kill",
                "returncode": 1,
                "error": f"{exc}; fallback={fallback_exc}",
            }


def redact_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return []
    if _looks_like_wsl_shell(cmd):
        return [cmd[0], cmd[1], cmd[2], cmd[3], "[shell-command-omitted]"]

    safe: list[str] = []
    for idx, token in enumerate(cmd):
        if idx >= 12:
            safe.append("[omitted]")
            break
        safe.append(_redact_token(token))
    return safe


def _looks_like_wsl_shell(cmd: list[str]) -> bool:
    return len(cmd) >= 5 and cmd[0].lower().endswith("wsl") and cmd[2:4] == ["sh", "-lc"]


def _redact_token(token: str) -> str:
    upper = token.upper()
    if len(token) > 200:
        return "[long-argument-omitted]"
    if any(marker in upper for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "SK-")):
        return "[redacted]"
    return token


def _process_payload(
    *,
    task_id: str,
    label: str,
    pid: int,
    status: str,
    started_at: str,
    timeout_sec: int,
    command: list[str],
    stdout_path: Path,
    stderr_path: Path,
    process_token: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "label": label,
        "pid": pid,
        "process_token": process_token,
        "status": status,
        "started_at": started_at,
        "timeout_sec": timeout_sec,
        "command": command,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    write_json_file(path, data)


def _append_stream_sentinel(stdout_path: Path, *, status: str, returncode: int | None, elapsed_sec: float) -> None:
    sentinel = {
        "type": "world.process",
        "event": "stream_closed",
        "status": status,
        "returncode": returncode,
        "elapsed_sec": elapsed_sec,
        "closed_at": _utc_now(),
    }
    try:
        with stdout_path.open("a", encoding="utf-8", errors="replace") as stream:
            stream.write(json.dumps(sentinel, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        return


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _tail_text(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
