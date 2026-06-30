from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.attempt_recording import AttemptMetricsRecorder
from orchestrator.db import TaskDB
from orchestrator.task_artifact_repair import TaskArtifactRepairService


def _service(tmp_path: Path) -> tuple[TaskArtifactRepairService, TaskDB, ArtifactStore]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    return (
        TaskArtifactRepairService(
            db=db,
            artifacts=artifacts,
            metrics_recorder=AttemptMetricsRecorder(db),
        ),
        db,
        artifacts,
    )


def _create_task(db: TaskDB, run_dir: Path, *, task_id: str = "t_repair", worker: str = "opencode") -> None:
    db.create_task(
        {
            "task_id": task_id,
            "project_id": "generic",
            "repo_path": str(run_dir.parent),
            "user_goal": "只读复核，不修改文件。",
            "status": "COMPLETED_WITH_ARTIFACTS",
            "created_at": "2026-06-30T00:00:00Z",
            "updated_at": "2026-06-30T00:01:00Z",
            "route_worker": worker,
            "route_model": "opencode_go_glm52",
            "route_variant": "high",
            "pr_url": None,
            "run_dir": str(run_dir),
        }
    )


def _write_repair_artifacts(artifacts: ArtifactStore, run_dir: Path, *, summary: str) -> Path:
    worker_dir = run_dir / "worker"
    worker_dir.mkdir(parents=True)
    stdout_path = worker_dir / "worker.stdout.jsonl"
    stdout_path.write_text(
        json.dumps({"type": "text", "part": {"text": "真实输出：项目质量良好，但 README check 描述偏窄。"}}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    artifacts.write_json("t_repair", "task.json", {"task_id": "t_repair", "status": "QUEUED"})
    artifacts.write_json(
        "t_repair",
        "result.json",
        {
            "status": "success",
            "summary": summary,
            "changed_files": [],
            "stdout_path": str(stdout_path),
        },
    )
    artifacts.write_json(
        "t_repair",
        "attempts/01/result.json",
        {
            "status": "success",
            "summary": summary,
            "changed_files": [],
            "stdout_path": str(stdout_path),
        },
    )
    artifacts.write_json("t_repair", "route.json", {"selected_worker": "opencode", "selected_model": "opencode_go_glm52"})
    artifacts.write_json("t_repair", "verify/verify.json", {"tests_passed": True, "build_passed": True})
    artifacts.write_json("t_repair", "review/review.json", {"approved": True, "review_mode": "skipped_read_only", "can_create_pr": False})
    return stdout_path


def test_sync_task_artifact_from_db_updates_task_json(tmp_path: Path) -> None:
    service, db, artifacts = _service(tmp_path)
    run_dir = artifacts.run_dir("t_repair")
    _create_task(db, run_dir)
    artifacts.write_json("t_repair", "task.json", {"task_id": "t_repair", "status": "QUEUED"})

    changed = service.sync_task_artifact_from_db("t_repair")

    task_json = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
    assert changed is True
    assert task_json["status"] == "COMPLETED_WITH_ARTIFACTS"
    assert task_json["route_worker"] == "opencode"
    assert task_json["route_variant"] == "high"


def test_repair_backfills_generic_opencode_summary(tmp_path: Path) -> None:
    service, db, artifacts = _service(tmp_path)
    run_dir = artifacts.run_dir("t_repair")
    _create_task(db, run_dir)
    _write_repair_artifacts(artifacts, run_dir, summary="OpenCode worker finished")

    result = service.repair_task_artifacts("t_repair")

    result_json = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    attempt_json = json.loads((run_dir / "attempts" / "01" / "result.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")
    metrics_json = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    assert result["repaired_count"] == 1
    assert result["repaired"][0]["changes"] == ["task_json_synced", "worker_result_backfilled"]
    assert "真实输出" in result_json["summary"]
    assert attempt_json["summary"] == result_json["summary"]
    assert "真实输出" in final_md
    assert metrics_json["worker"] == "opencode"


def test_repair_does_not_overwrite_specific_summary(tmp_path: Path) -> None:
    service, db, artifacts = _service(tmp_path)
    run_dir = artifacts.run_dir("t_repair")
    _create_task(db, run_dir)
    _write_repair_artifacts(artifacts, run_dir, summary="Specific existing analysis.")

    result = service.repair_task_artifacts("t_repair")

    result_json = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["repaired_count"] == 1
    assert result["repaired"][0]["changes"] == ["task_json_synced"]
    assert result_json["summary"] == "Specific existing analysis."
