from __future__ import annotations

from pathlib import Path

from orchestrator.world_runtime_service import WorldRuntimeService, safe_parallelism_from_profile


def _service() -> WorldRuntimeService:
    return WorldRuntimeService(
        profile_project=lambda repo_path, force=False: {
            "profile": {
                "detected_types": ["python"],
                "test_commands": ["pytest"],
                "build_commands": [],
            }
        },
        detect_project=lambda **kwargs: {"project_id": "demo", "needs_user": False},
        model_metrics_summary=lambda: [],
        new_run_id=lambda: "t_20260630_000000_abcdef",
    )


def test_world_runtime_bootstrap_writes_external_profile(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))

    result = _service().bootstrap(str(repo), "use world")

    assert result["world_enabled"] is True
    assert result["project_id"] == "demo"
    assert result["runtime_id"]
    assert Path(result["project_profile_path"]).exists()
    assert not (repo / ".world").exists()


def test_world_runtime_create_plan_uses_profile_and_external_store(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))

    result = _service().create_plan(str(repo), "Update README", "low")

    plan = result["plan"]
    assert plan["run_id"].startswith("world_")
    assert plan["repo_path"] == str(repo.resolve())
    assert plan["safe_parallelism"] == 2
    assert plan["route"]["selected_worker"] == "claude_code"
    assert Path(result["plan_path"]).exists()
    assert str(repo) not in result["plan_path"]


def test_safe_parallelism_from_profile_is_conservative() -> None:
    assert safe_parallelism_from_profile({"profile": {"safe_parallelism": 3}}) == 3
    assert safe_parallelism_from_profile({"profile": {"detected_types": ["android_gradle", "python"]}}) == 1
    assert safe_parallelism_from_profile({"profile": {"detected_types": ["node"]}}) == 2
    assert safe_parallelism_from_profile({}) == 1
