from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.stale_worker_reaper import StaleWorkerReaper
from orchestrator.verifier import VerifyResult


def _verify(task: dict) -> VerifyResult:
    diff_path = Path(task["run_dir"]) / "verify" / "diff.patch"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("", encoding="utf-8")
    return VerifyResult(
        tests_passed=True,
        build_passed=True,
        command_results=[],
        changed_files=[],
        diff_path=str(diff_path),
        forbidden_allowed=True,
        command_permissions_allowed=True,
        finished_at="2026-06-30T00:00:00Z",
    )


def _task(run_dir: Path, *, status: str = "EXECUTING") -> dict:
    return {
        "task_id": "t_reap",
        "project_id": "generic",
        "repo_path": str(run_dir.parent),
        "user_goal": "只读分析项目，不修改文件。",
        "status": status,
        "created_at": "2026-06-30T00:00:00Z",
        "updated_at": "2026-06-30T00:00:00Z",
        "route_worker": "claude_code",
        "route_model": "deepseek_pro",
        "run_dir": str(run_dir),
        "test_commands": ["pytest"],
    }


def _write_control(run_dir: Path, stdout_path: Path) -> None:
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True)
    (control_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "status": "running", "stdout_path": str(stdout_path)}),
        encoding="utf-8",
    )
    (control_dir / "heartbeat.json").write_text(json.dumps({"last_seen": 1000}), encoding="utf-8")


def _reaper(tmp_path: Path) -> StaleWorkerReaper:
    return StaleWorkerReaper(
        artifacts=ArtifactStore(tmp_path / "runs"),
        dry_verify_func=_verify,
        task_requires_diff=lambda task: False,
        now_func=lambda: 1200,
        pid_alive_func=lambda pid: False,
        stale_after_sec=120,
    )


def test_reap_recovers_read_only_success_stream(tmp_path: Path) -> None:
    reaper = _reaper(tmp_path)
    run_dir = reaper.artifacts.run_dir("t_reap")
    stdout_path = run_dir / "worker" / "worker.stream.jsonl"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text(
        json.dumps({"type": "result", "subtype": "success", "result": "## Summary\n\nCompleted read-only analysis."})
        + "\n",
        encoding="utf-8",
    )
    _write_control(run_dir, stdout_path)

    result = reaper.reap(_task(run_dir))

    process = json.loads((run_dir / "control" / "process.json").read_text(encoding="utf-8"))
    review = json.loads((run_dir / "review" / "review.json").read_text(encoding="utf-8"))
    worker_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))

    assert result is not None
    assert result.status == "COMPLETED_WITH_ARTIFACTS"
    assert result.event_type == "stale_worker_reaped"
    assert process["status"] == "reaped"
    assert review["review_mode"] == "skipped_read_only"
    assert worker_result["changed_files"] == []
    assert (run_dir / "final.md").exists()


def test_reap_fails_stale_task_without_recoverable_result(tmp_path: Path) -> None:
    reaper = _reaper(tmp_path)
    run_dir = reaper.artifacts.run_dir("t_reap")
    stdout_path = run_dir / "worker" / "worker.stream.jsonl"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text(json.dumps({"type": "result", "subtype": "failed", "result": "failed"}) + "\n", encoding="utf-8")
    _write_control(run_dir, stdout_path)

    result = reaper.reap(_task(run_dir))

    process = json.loads((run_dir / "control" / "process.json").read_text(encoding="utf-8"))

    assert result is not None
    assert result.status == "FAILED_FINAL"
    assert result.event_type == "stale_worker_failed"
    assert process["status"] == "failed"
    assert not (run_dir / "final.md").exists()


def test_reap_ignores_fresh_heartbeat(tmp_path: Path) -> None:
    reaper = StaleWorkerReaper(
        artifacts=ArtifactStore(tmp_path / "runs"),
        dry_verify_func=_verify,
        task_requires_diff=lambda task: False,
        now_func=lambda: 1050,
        pid_alive_func=lambda pid: False,
        stale_after_sec=120,
    )
    run_dir = reaper.artifacts.run_dir("t_reap")
    stdout_path = run_dir / "worker" / "worker.stream.jsonl"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text("", encoding="utf-8")
    _write_control(run_dir, stdout_path)

    assert reaper.reap(_task(run_dir)) is None
