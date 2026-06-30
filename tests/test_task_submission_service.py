from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB
from orchestrator.task_submission import TaskSubmissionBuilder
from orchestrator.task_submission_service import TaskSubmissionService


class FakeCodexUsageRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_planning_dispatch(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _project(tmp_path: Path) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    return {
        "repo": str(repo),
        "test_commands": ["uv run pytest"],
        "build_commands": [],
        "forbidden_paths": [".env"],
        "allow_auto_pr": False,
        "world": {"write_policy": "zero_write"},
    }


def _service(
    tmp_path: Path,
    *,
    projects: dict[str, dict[str, Any]] | None = None,
    executed: list[dict[str, Any]] | None = None,
) -> tuple[TaskSubmissionService, TaskDB, ArtifactStore, FakeCodexUsageRecorder]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    usage = FakeCodexUsageRecorder()
    executed = executed if executed is not None else []

    def execute_task(task: dict[str, Any], project: dict[str, Any], dry_run: bool) -> None:
        executed.append({"task": task, "project": project, "dry_run": dry_run})
        db.update_task(task["task_id"], status="DRY_RUN_COMPLETED" if dry_run else "EXECUTING", updated_at="2026-07-01T00:00:01Z")

    return (
        TaskSubmissionService(
            db=db,
            artifacts=artifacts,
            submission_builder=TaskSubmissionBuilder(),
            codex_usage=usage,  # type: ignore[arg-type]
            load_projects_func=lambda: projects or {"demo": _project(tmp_path)},
            new_task_id=lambda: "t_submit",
            now=lambda: "2026-07-01T00:00:00Z",
            execute_task=execute_task,
            get_task_status=lambda task_id: db.get_task(task_id) or {"status": "NOT_FOUND"},
        ),
        db,
        artifacts,
        usage,
    )


def test_submit_task_returns_needs_user_for_unknown_project(tmp_path: Path):
    service, _, _, _ = _service(tmp_path, projects={})

    result = service.submit_task("missing", "inspect")

    assert result == {"status": "NEEDS_USER", "message": "unknown project_id: missing"}


def test_submit_task_persists_task_artifacts_and_codex_usage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    service, db, _, usage = _service(tmp_path)

    result = service.submit_task(
        "demo",
        "Inspect repo",
        risk_level="low",
        auto_execute=False,
        auto_pr=True,
        dry_run=True,
        force_worker="claude_code",
        force_model="deepseek_flash",
        task_mode="read_only",
        expected_diff=False,
        verification_policy="changed_files_only",
        read_budget_profile="quick_triage",
    )

    task = db.get_task("t_submit")
    assert result["status"] == "QUEUED"
    assert task is not None
    assert task["project_id"] == "demo"
    assert task["status"] == "QUEUED"
    assert db.list_events("t_submit")[-1]["event_type"] == "created"
    task_json = json.loads((Path(result["run_dir"]) / "task.json").read_text(encoding="utf-8"))
    assert task_json["task_mode"] == "read_only"
    assert task_json["auto_pr"] is False
    assert usage.calls[0]["dry_run"] is True
    assert usage.calls[0]["auto_pr"] is False
    assert usage.calls[0]["force_worker"] == "claude_code"
    assert usage.calls[0]["has_images"] is False


def test_submit_task_auto_execute_invokes_execution_callback(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    executed: list[dict[str, Any]] = []
    service, _, _, _ = _service(tmp_path, executed=executed)

    result = service.submit_task("demo", "Run dry task", auto_execute=True, dry_run=True)

    assert result["status"] == "DRY_RUN_COMPLETED"
    assert executed[0]["task"]["task_id"] == "t_submit"
    assert executed[0]["project"]["repo"]
    assert executed[0]["dry_run"] is True
