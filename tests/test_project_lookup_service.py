from __future__ import annotations

from pathlib import Path

from orchestrator.project_lookup_service import ProjectLookupService, project_registration_health
from orchestrator.project_registry import ProjectMatch


def test_list_projects_filters_by_project_id_or_name():
    service = ProjectLookupService(
        load_projects_func=lambda: {
            "travel_with_me": {"project_id": "travel_with_me", "name": "Travel With Me"},
            "world_system": {"project_id": "world_system", "name": "World"},
        }
    )

    result = service.list_projects("travel")

    assert result["projects"] == [{"project_id": "travel_with_me", "name": "Travel With Me"}]


def test_detect_project_adds_health_payload(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    project = {
        "project_id": "demo",
        "name": "Demo",
        "repo": str(repo),
        "test_commands": ["uv run pytest"],
        "build_commands": [],
        "allow_auto_pr": False,
    }
    service = ProjectLookupService(
        detect_project_func=lambda **kwargs: ProjectMatch("demo", 1.0, "repo_path", False, project)
    )

    result = service.detect_project(repo_path=str(repo))

    assert result["project_id"] == "demo"
    assert result["health"] == {"status": "ok", "issues": [], "warnings": ["build_commands is empty"]}


def test_project_registration_health_reports_missing_and_unsafe_registration(tmp_path: Path):
    requested = tmp_path / "requested"
    requested.mkdir()
    registered = tmp_path / "registered"
    registered.mkdir()

    result = project_registration_health(
        {
            "repo": str(registered),
            "allow_auto_pr": True,
            "test_commands": "pytest",
            "build_commands": [],
        },
        requested_repo_path=str(requested),
    )

    assert result["status"] == "needs_fix"
    assert f"registered repo path differs from requested path: {registered}" in result["issues"]
    assert "allow_auto_pr is enabled; World deployment policy expects false unless explicitly approved" in result["issues"]
    assert "test_commands must be a list" in result["issues"]
    assert "build_commands is empty" in result["warnings"]


def test_project_registration_health_reports_unknown_project():
    assert project_registration_health(None) == {
        "status": "unknown",
        "issues": ["project is not registered"],
        "warnings": [],
    }
