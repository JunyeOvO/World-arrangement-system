from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.attempt_recording import AttemptMetricsRecorder
from orchestrator.db import TaskDB
from orchestrator.worker_attempt_executor import WorkerAttemptExecutor
from orchestrator.worker_permission_audit import WorkerPermissionAuditor
from orchestrator.workers.base import Worker, WorkerResult


class SuccessWorker(Worker):
    name = "success_worker"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        stream = Path(task["run_dir"]) / "worker" / "worker.stream.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(
            json.dumps({"type": "result", "subtype": "success", "usage": {"input_tokens": 100, "output_tokens": 20}})
            + "\n",
            encoding="utf-8",
        )
        return WorkerResult(status="success", summary=f"handled: {prompt}", stdout_path=str(stream))


class ExplodingWorker(Worker):
    name = "exploding_worker"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        raise RuntimeError("worker exploded")


def test_worker_attempt_executor_success_records_artifacts_metrics_and_events(tmp_path):
    db, run_dir = _task_db(tmp_path, "t_attempt_success")
    artifacts = ArtifactStore(tmp_path / "runs")
    statuses: list[tuple[str, str, str]] = []
    executor = WorkerAttemptExecutor(
        artifacts=artifacts,
        permission_auditor=WorkerPermissionAuditor(db),
        metrics_recorder=AttemptMetricsRecorder(db),
        workers={"fake": SuccessWorker()},
        default_worker=SuccessWorker(),
        now=lambda: "2026-06-30T01:00:02Z",
        set_status=lambda task_id, status, event, payload: statuses.append((task_id, status, event)),
        build_prompt=lambda task, route: f"goal={task['user_goal']}; model={route['selected_model']}",
    )

    outcome = executor.run(
        task_id="t_attempt_success",
        task={"task_id": "t_attempt_success", "run_dir": str(run_dir), "user_goal": "inspect", "project_id": "p1"},
        worktree_path=tmp_path,
        attempt={"worker": "fake", "model": "demo_model"},
        attempt_no=1,
    )

    assert outcome.kind == "completed"
    assert outcome.worker_result.status == "success"
    assert statuses == [("t_attempt_success", "EXECUTING", "worker_started")]
    assert json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["status"] == "success"
    assert json.loads((run_dir / "attempts" / "01" / "metrics.json").read_text(encoding="utf-8"))["input_tokens"] == 100
    assert (run_dir / "token_ledger.json").exists()
    assert db.list_events("t_attempt_success")[-1]["event_type"] == "permission_diff_checked"


def test_worker_attempt_executor_exception_returns_normalized_failure(tmp_path):
    db, run_dir = _task_db(tmp_path, "t_attempt_exception")
    executor = WorkerAttemptExecutor(
        artifacts=ArtifactStore(tmp_path / "runs"),
        permission_auditor=WorkerPermissionAuditor(db),
        metrics_recorder=AttemptMetricsRecorder(db),
        workers={"fake": ExplodingWorker()},
        default_worker=ExplodingWorker(),
        now=lambda: "2026-06-30T01:00:02Z",
        set_status=lambda task_id, status, event, payload: None,
        build_prompt=lambda task, route: "prompt",
    )

    outcome = executor.run(
        task_id="t_attempt_exception",
        task={"task_id": "t_attempt_exception", "run_dir": str(run_dir), "user_goal": "inspect", "project_id": "p1"},
        worktree_path=tmp_path,
        attempt={"worker": "fake", "model": "demo_model"},
        attempt_no=1,
    )

    attempt_payload = json.loads((run_dir / "attempts" / "01" / "result.json").read_text(encoding="utf-8"))
    assert outcome.kind == "worker_exception"
    assert outcome.failure.failure_reason == "worker_exception"
    assert attempt_payload["status"] == "failed"
    assert "worker exploded" in attempt_payload["failure"]["evidence"][0]


def _task_db(tmp_path: Path, task_id: str) -> tuple[TaskDB, Path]:
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "task.json").write_text("{}", encoding="utf-8")
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": task_id,
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "inspect",
            "status": "WORKTREE_READY",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(run_dir),
        }
    )
    return db, run_dir
