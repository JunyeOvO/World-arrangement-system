from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .control_files import read_json_file, write_json_file
from .read_only_completion import extract_worker_success_text, read_only_review
from .task_result_document import build_final_markdown
from .verifier import VerifyResult, write_verify_result


@dataclass
class StaleWorkerReapResult:
    status: str
    event_type: str
    payload: dict[str, Any]


class StaleWorkerReaper:
    """Recovers or fails stale worker tasks whose process has stopped heartbeating."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        dry_verify_func: Callable[[dict[str, Any]], VerifyResult],
        task_requires_diff: Callable[[dict[str, Any]], bool],
        now_func: Callable[[], float] = time.time,
        pid_alive_func: Callable[[int], bool] | None = None,
        stale_after_sec: int = 120,
    ) -> None:
        self.artifacts = artifacts
        self.dry_verify_func = dry_verify_func
        self.task_requires_diff = task_requires_diff
        self.now_func = now_func
        self.pid_alive_func = pid_alive_func or pid_is_alive
        self.stale_after_sec = stale_after_sec

    def reap(self, task: dict[str, Any]) -> StaleWorkerReapResult | None:
        status = str(task.get("status") or "")
        if status not in {"EXECUTING", "RUNNING", "VERIFYING", "CODEX_REVIEWING", "REVIEWING"}:
            return None
        run_dir = Path(str(task.get("run_dir") or ""))
        control_dir = run_dir / "control"
        process = read_json_if_exists(control_dir / "process.json") or {}
        heartbeat = read_json_if_exists(control_dir / "heartbeat.json") or {}
        if str(process.get("status") or "") != "running":
            return None
        last_seen_ts = parse_timestamp(heartbeat.get("last_seen") or heartbeat.get("ts"))
        if last_seen_ts is None:
            return None
        if self.now_func() - last_seen_ts < self.stale_after_sec:
            return None
        pid = process.get("pid")
        process_token = str(process.get("process_token") or "")
        heartbeat_token = str(heartbeat.get("process_token") or "")
        if process_token and heartbeat_token and process_token != heartbeat_token:
            return self._fail_stale_task(
                task,
                process,
                control_dir,
                reason="heartbeat token does not match process token",
            )
        if not process_token and isinstance(pid, int) and self.pid_alive_func(pid):
            return None

        stdout_path = Path(str(process.get("stdout_path") or run_dir / "worker" / "worker.stream.jsonl"))
        result_text = extract_worker_success_text(stdout_path)
        if result_text and not self.task_requires_diff(task):
            return self._recover_read_only_success(task, process, control_dir, stdout_path, result_text)
        return self._fail_stale_task(task, process, control_dir)

    def _recover_read_only_success(
        self,
        task: dict[str, Any],
        process: dict[str, Any],
        control_dir: Path,
        stdout_path: Path,
        result_text: str,
    ) -> StaleWorkerReapResult:
        task_id = str(task["task_id"])
        worker_payload = {
            "status": "success",
            "summary": result_text,
            "changed_files": [],
            "test_suggestions": task.get("test_commands", []),
            "risks": ["reaped_from_stale_worker_stream"],
            "needs_orchestrator_action": False,
            "stdout_path": str(stdout_path),
            "stderr_path": str(process.get("stderr_path") or ""),
            "patch_file": None,
            "tests_run": [],
            "rollback_notes": "No diff to export",
            "degraded": False,
            "degradation_reason": None,
            "mock_result": False,
        }
        run_dir = Path(str(task["run_dir"]))
        verify_result = self.dry_verify_func(task)
        review = read_only_review(task, reason="stale_worker_reaped")
        self.artifacts.write_json(task_id, "result.json", worker_payload)
        write_verify_result(verify_result, run_dir / "verify" / "verify.json")
        self.artifacts.write_json(task_id, "verify/changed_files.json", [])
        self.artifacts.write_json(task_id, "review/review.json", review)
        route = {
            "selected_worker": task.get("route_worker") or "unknown",
            "selected_model": task.get("route_model") or "unknown",
        }
        self.artifacts.write_text(
            task_id,
            "final.md",
            build_final_markdown(task, route, worker_payload, verify_result.to_dict(), review),
        )
        process.update({"status": "reaped", "finished_at": now_iso(), "reaped_reason": "stale_worker_success_stream"})
        write_json_file(control_dir / "process.json", process)
        return StaleWorkerReapResult(
            status="COMPLETED_WITH_ARTIFACTS",
            event_type="stale_worker_reaped",
            payload={"reason": "stale worker had success result in stream", "stdout_path": str(stdout_path)},
        )

    def _fail_stale_task(
        self,
        task: dict[str, Any],
        process: dict[str, Any],
        control_dir: Path,
        reason: str = "worker process is not alive and no recoverable success result was found",
    ) -> StaleWorkerReapResult:
        process.update({"status": "failed", "finished_at": now_iso(), "reaped_reason": "stale_worker_no_live_pid"})
        write_json_file(control_dir / "process.json", process)
        return StaleWorkerReapResult(
            status="FAILED_FINAL",
            event_type="stale_worker_failed",
            payload={"reason": reason},
        )


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read_json_file(path)
    except (OSError, TimeoutError):
        return {"unreadable": str(path)}


def parse_timestamp(value: Any) -> float | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
