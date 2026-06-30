from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB
from orchestrator.task_outcome_recording import TaskOutcomeRecorder


def _recorder(tmp_path: Path) -> tuple[TaskOutcomeRecorder, TaskDB, ArtifactStore]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    return TaskOutcomeRecorder(db=db, artifacts=artifacts), db, artifacts


def test_record_task_outcome_writes_db_and_artifact(tmp_path: Path) -> None:
    recorder, db, artifacts = _recorder(tmp_path)
    run_dir = artifacts.run_dir("t_outcome")
    db.create_task(
        {
            "task_id": "t_outcome",
            "project_id": "generic",
            "repo_path": str(tmp_path / "repo"),
            "user_goal": "只读分析项目质量",
            "status": "COMPLETED_WITH_ARTIFACTS",
            "created_at": "2026-06-30T00:00:00Z",
            "updated_at": "2026-06-30T00:01:00Z",
            "route_worker": "claude_code",
            "route_model": "deepseek_pro",
            "route_variant": "",
            "pr_url": None,
            "run_dir": str(run_dir),
        }
    )
    db.upsert_task_metrics(
        {
            "task_id": "t_outcome",
            "attempt_no": 1,
            "worker": "claude_code",
            "model": "deepseek_pro",
            "status": "success",
            "changed_files_count": 0,
            "build_passed": True,
            "review_approved": True,
            "created_at": "2026-06-30T00:01:00Z",
        }
    )
    artifacts.write_json("t_outcome", "task.json", {"task_type": "read_only_analysis", "risk_level": "low"})
    artifacts.write_json("t_outcome", "verify/verify.json", {"tests_passed": True, "build_passed": True, "changed_files": []})
    artifacts.write_json("t_outcome", "review/review.json", {"approved": True, "review_mode": "skipped_read_only"})
    artifacts.write_json("t_outcome", "result.json", {"changed_files": []})

    recorder.record_task_outcome("t_outcome", metadata={"source": "unit_test"})

    db_row = db.get_task_outcome("t_outcome")
    artifact_row = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    assert db_row is not None
    assert db_row["outcome"] == "success"
    assert db_row["quality_state"] == "verified"
    assert db_row["user_acceptance"] == "accepted"
    assert artifact_row["metadata"]["source"] == "unit_test"
    assert artifact_row["metadata"]["metric_attempts"] == 1


def test_record_task_outcome_ignores_missing_task(tmp_path: Path) -> None:
    recorder, db, artifacts = _recorder(tmp_path)

    recorder.record_task_outcome("missing")

    assert db.get_task_outcome("missing") is None
    assert not (artifacts.root / "missing").exists()
