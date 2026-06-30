from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.artifacts import ArtifactStore
from orchestrator.attempt_recording import AttemptMetricsRecorder
from orchestrator.db import TaskDB
from orchestrator.task_artifact_repair import TaskArtifactRepairService
from orchestrator.task_operations import TaskOperationsService


def _service(tmp_path: Path) -> tuple[TaskOperationsService, TaskDB, ArtifactStore, list[dict[str, Any]]]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    repairs = TaskArtifactRepairService(
        db=db,
        artifacts=artifacts,
        metrics_recorder=AttemptMetricsRecorder(db),
    )
    policy_calls: list[dict[str, Any]] = []

    def reap(task: dict[str, Any]) -> None:
        if task["status"] == "EXECUTING":
            db.update_task(task["task_id"], status="COMPLETED_WITH_ARTIFACTS", updated_at="2026-07-01T00:00:10Z")
            db.append_event(
                task["task_id"],
                "reaped",
                "EXECUTING",
                "COMPLETED_WITH_ARTIFACTS",
                {"source": "test"},
            )

    def record_policy(task: dict[str, Any], route: dict[str, Any], **kwargs: Any) -> None:
        policy_calls.append({"task": task, "route": route, "kwargs": kwargs})

    service = TaskOperationsService(
        db=db,
        artifacts=artifacts,
        artifact_repair=repairs,
        reap_stale_worker_task=reap,
        record_policy_learning=record_policy,
        write_token_ledger=AttemptMetricsRecorder(db).write_token_ledger,
        now=lambda: "2026-07-01T00:00:20Z",
    )
    return service, db, artifacts, policy_calls


def _create_task(db: TaskDB, run_dir: Path, *, task_id: str = "t_ops", status: str = "COMPLETED_WITH_ARTIFACTS") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    db.create_task(
        {
            "task_id": task_id,
            "project_id": "project_1",
            "repo_path": str(run_dir.parent / "repo"),
            "user_goal": "inspect project",
            "status": status,
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:01Z",
            "run_dir": str(run_dir),
            "route_worker": "claude_code",
            "route_model": "deepseek_flash",
        }
    )


def test_get_task_status_refreshes_stale_state_and_returns_recent_events(tmp_path: Path):
    service, db, _, _ = _service(tmp_path)
    run_dir = tmp_path / "runs" / "t_ops"
    _create_task(db, run_dir, status="EXECUTING")

    result = service.get_task_status("t_ops")

    assert result["status"] == "COMPLETED_WITH_ARTIFACTS"
    assert result["events"][-1]["event_type"] == "reaped"


def test_read_task_result_returns_index_and_truncated_artifacts(tmp_path: Path):
    service, db, artifacts, _ = _service(tmp_path)
    task_id = "t_ops"
    _create_task(db, tmp_path / "runs" / task_id, task_id=task_id)
    artifacts.write_text(task_id, "final.md", "x" * 21000)
    artifacts.write_json(task_id, "metrics.json", {"status": "success"})

    result = service.read_task_result(task_id)

    assert result["task"]["task_id"] == task_id
    assert "final.md" in result["artifacts"]
    assert len(result["final.md"]) == 20000
    assert json.loads(result["metrics.json"]) == {"status": "success"}


def test_cancel_task_writes_control_request_and_cancel_event(tmp_path: Path):
    service, db, _, _ = _service(tmp_path)
    task_id = "t_cancel"
    run_dir = tmp_path / "runs" / task_id
    _create_task(db, run_dir, task_id=task_id, status="EXECUTING")

    result = service.cancel_task(task_id, reason="user requested stop")

    assert result["status"] == "CANCELLED"
    control = json.loads((run_dir / "control" / "cancel.requested").read_text(encoding="utf-8"))
    assert control["reason"] == "user requested stop"
    assert db.list_events(task_id)[-1]["event_type"] == "cancelled"


def test_get_task_control_reports_unreadable_json(tmp_path: Path):
    service, db, _, _ = _service(tmp_path)
    task_id = "t_control"
    run_dir = tmp_path / "runs" / task_id
    _create_task(db, run_dir, task_id=task_id)
    control_dir = run_dir / "control"
    control_dir.mkdir()
    (control_dir / "process.json").write_text("{not-json", encoding="utf-8")

    result = service.get_task_control(task_id)

    assert result["process"] == {"unreadable": str(control_dir / "process.json")}


def test_rollback_task_records_policy_learning_signal(tmp_path: Path):
    service, db, _, policy_calls = _service(tmp_path)
    task_id = "t_rollback"
    _create_task(db, tmp_path / "runs" / task_id, task_id=task_id)

    result = service.rollback_task(task_id, cleanup_worktree=False)

    assert result["status"] == "ROLLED_BACK"
    assert db.list_events(task_id)[-1]["event_type"] == "rolled_back"
    assert policy_calls[-1]["kwargs"]["rollback"] is True
    assert policy_calls[-1]["kwargs"]["success"] is False


def test_record_task_baseline_writes_artifact_and_refreshes_token_ledger(tmp_path: Path):
    service, db, artifacts, _ = _service(tmp_path)
    task_id = "t_baseline"
    run_dir = tmp_path / "runs" / task_id
    _create_task(db, run_dir, task_id=task_id)
    artifacts.write_text(task_id, "final.md", "# Done\n")

    result = service.record_task_baseline(task_id)

    assert result["status"] == "BASELINE_RECORDED"
    assert (run_dir / "baselines" / "task_baselines.jsonl").exists()
    ledger = json.loads((run_dir / "token_ledger.json").read_text(encoding="utf-8"))
    assert ledger["counterfactual"]["status"] == "estimated"
    assert ledger["baselines"][0]["source"] == "replay_estimate"
