from __future__ import annotations

from pathlib import Path

from orchestrator.task_submission import TaskSubmissionBuilder


def _project(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    return {
        "repo": str(repo),
        "test_commands": ["pytest"],
        "build_commands": ["python -m compileall app"],
        "forbidden_paths": [".env"],
        "allow_auto_pr": True,
        "world": {"write_policy": "zero_write"},
    }


def test_submission_builder_normalizes_protocol_and_project_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    run_dir = tmp_path / "run"

    submission = TaskSubmissionBuilder().build(
        task_id="t_submit",
        run_dir=run_dir,
        now="2026-07-01T00:00:00Z",
        project_id="demo",
        project=_project(tmp_path),
        user_goal="只读调查 3D workArea 数据契约风险",
        risk_level="medium",
        auto_execute=True,
        auto_pr=True,
        image_paths=None,
        image_base64=None,
    )

    task = submission.task
    assert task["task_id"] == "t_submit"
    assert task["project_id"] == "demo"
    assert task["status"] == "QUEUED"
    assert task["auto_pr"] is True
    assert task["auto_merge"] is False
    assert task["test_commands"] == ["pytest"]
    assert task["build_commands"] == ["python -m compileall app"]
    assert task["forbidden_paths"] == [".env"]
    assert task["image_paths"] == []
    assert task["image_base64"] == []
    assert task["task_mode"] == "read_only"
    assert task["expected_diff"] is False
    assert task["read_budget_profile"] == "code_contract_audit"
    assert submission.protocol == {
        "task_mode": task["task_mode"],
        "expected_diff": task["expected_diff"],
        "verification_policy": task["verification_policy"],
        "read_budget_profile": task["read_budget_profile"],
        "read_budget": task["read_budget"],
    }
    assert "project_memory" in task
    assert task["project_memory"]["memory"]["source_kind"] == "registered_repo"
    assert submission.project_memory == task["project_memory"]


def test_submission_builder_respects_auto_pr_policy_and_route_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    project = _project(tmp_path)
    project["allow_auto_pr"] = False

    submission = TaskSubmissionBuilder().build(
        task_id="t_submit",
        run_dir=tmp_path / "run",
        now="2026-07-01T00:00:00Z",
        project_id="demo",
        project=project,
        user_goal="Fix bug",
        risk_level="low",
        auto_execute=False,
        auto_pr=True,
        force_worker="opencode",
        force_model="opencode_go_glm52",
        force_variant="high",
        image_paths=["a.png"],
        image_base64=["data:image/png;base64,abc"],
        task_mode="patch",
        expected_diff=True,
        verification_policy="unit",
        read_budget_profile="quick_triage",
        read_budget={"max_files": 3},
    )

    task = submission.task
    assert task["auto_execute"] is False
    assert task["auto_pr"] is False
    assert task["route_override"] == {
        "worker": "opencode",
        "model": "opencode_go_glm52",
        "variant": "high",
    }
    assert task["image_paths"] == ["a.png"]
    assert task["image_base64"] == ["data:image/png;base64,abc"]
    assert task["verification_policy"] == "unit"
    assert task["read_budget"]["max_files"] == 3
