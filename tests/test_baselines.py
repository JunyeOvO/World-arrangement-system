from __future__ import annotations

import json
import subprocess
import sys

from orchestrator.baselines import build_manual_baseline, build_replay_baseline
from orchestrator.db import TaskDB
from orchestrator.scheduler import OrchestratorService
from orchestrator.token_ledger import build_task_token_ledger


def _create_task(db: TaskDB, tmp_path, task_id: str = "task_1") -> None:
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db.create_task({
        "task_id": task_id,
        "project_id": "project_1",
        "repo_path": str(tmp_path / "repo"),
        "user_goal": "fix a production bug",
        "status": "COMPLETED_WITH_PATCH",
        "created_at": "2026-06-29T01:00:00Z",
        "updated_at": "2026-06-29T01:01:00Z",
        "run_dir": str(run_dir),
    })
    db.record_codex_usage_event({
        "task_id": task_id,
        "phase": "planning_dispatch",
        "model": "codex",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "actual_codex_used": False,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-29T01:00:01Z",
        "metadata": {},
    })


def test_replay_baseline_uses_task_artifacts(tmp_path):
    final_md = tmp_path / "final.md"
    final_md.write_text("# Result\n\nFixed the bug.\n", encoding="utf-8")
    verify = tmp_path / "verify.json"
    verify.write_text(json.dumps({"tests_passed": True}), encoding="utf-8")

    baseline = build_replay_baseline(
        task={"task_id": "task_1", "project_id": "project_1", "user_goal": "fix bug"},
        artifact_index={"final.md": str(final_md), "verify/verify.json": str(verify)},
    )

    assert baseline["task_id"] == "task_1"
    assert baseline["source"] == "replay_estimate"
    assert baseline["total_tokens"] > 0
    assert baseline["actual_codex_used"] is False


def test_replay_baseline_metadata_filters_runtime_artifacts(tmp_path):
    final_md = tmp_path / "final.md"
    final_md.write_text("# Result\n\nRead-only output.\n", encoding="utf-8")
    worker_stream = tmp_path / "worker.stream.jsonl"
    worker_stream.write_text("large stream\n", encoding="utf-8")

    baseline = build_replay_baseline(
        task={"task_id": "task_1", "project_id": "project_1", "user_goal": "inspect"},
        artifact_index={
            "final.md": str(final_md),
            "worktrees/task_1/app.ts": str(tmp_path / "app.ts"),
            "worker/worker.stream.jsonl": str(worker_stream),
            "control/process.json": str(tmp_path / "process.json"),
        },
    )

    assert baseline["metadata"]["artifact_paths"] == ["final.md"]
    assert baseline["metadata"]["artifact_count"] == 4
    assert baseline["metadata"]["excluded_runtime_artifact_count"] == 3


def test_db_records_task_baseline_and_token_ledger_uses_actual_first(tmp_path):
    db = TaskDB(tmp_path / "world.db")
    _create_task(db, tmp_path)
    db.record_task_baseline(build_replay_baseline(
        task=db.get_task("task_1") or {},
        artifact_index={},
    ))
    db.record_task_baseline(build_manual_baseline(
        task_id="task_1",
        input_tokens=1000,
        output_tokens=500,
        actual_codex_used=True,
    ))

    baselines = db.list_task_baselines("task_1")
    ledger = build_task_token_ledger(db, "task_1")

    assert baselines[0]["actual_codex_used"] is True
    assert ledger["counterfactual"]["status"] == "measured"
    assert ledger["counterfactual"]["baseline_total_tokens"] == 1500
    assert ledger["counterfactual"]["world_codex_total_tokens"] == 150
    assert ledger["counterfactual"]["codex_tokens_saved"] == 1350


def test_service_record_task_baseline_writes_artifact_and_refreshes_ledger(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    service = OrchestratorService()
    task_id = "task_1"
    run_dir = service.paths.runs / task_id
    service.db.create_task({
        "task_id": task_id,
        "project_id": "project_1",
        "repo_path": str(tmp_path / "repo"),
        "user_goal": "inspect repo",
        "status": "COMPLETED_WITH_ARTIFACTS",
        "created_at": "2026-06-29T01:00:00Z",
        "updated_at": "2026-06-29T01:01:00Z",
        "run_dir": str(run_dir),
    })
    service.artifacts.write_text(task_id, "final.md", "# Done\n")

    result = service.record_task_baseline(task_id)

    assert result["status"] == "BASELINE_RECORDED"
    assert (run_dir / "baselines" / "task_baselines.jsonl").exists()
    ledger = json.loads((run_dir / "token_ledger.json").read_text(encoding="utf-8"))
    assert ledger["counterfactual"]["status"] == "estimated"
    assert ledger["baselines"][0]["source"] == "replay_estimate"


def test_cli_record_task_baseline_with_manual_tokens(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    service = OrchestratorService()
    task_id = "task_1"
    service.db.create_task({
        "task_id": task_id,
        "project_id": "project_1",
        "repo_path": str(tmp_path / "repo"),
        "user_goal": "inspect repo",
        "status": "COMPLETED_WITH_ARTIFACTS",
        "created_at": "2026-06-29T01:00:00Z",
        "updated_at": "2026-06-29T01:01:00Z",
        "run_dir": str(service.paths.runs / task_id),
    })

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.cli",
            "record-task-baseline",
            "--task-id",
            task_id,
            "--input-tokens",
            "1200",
            "--output-tokens",
            "300",
            "--actual",
        ],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "BASELINE_RECORDED"
    assert payload["baseline"]["actual_codex_used"] is True
    assert payload["baseline"]["total_tokens"] == 1500
