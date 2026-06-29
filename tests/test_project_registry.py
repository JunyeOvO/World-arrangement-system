from pathlib import Path

from orchestrator.config import code_root
from orchestrator.project_registry import detect_project, load_projects


def test_ai_project_marker(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "projects.yaml").write_text(
        "projects:\n  demo:\n    project_id: demo\n    name: Demo\n    repo: /tmp/demo\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ai-project.yaml").write_text("project_id: demo\n", encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    match = detect_project(repo_path=str(repo))
    assert match.project_id == "demo"
    assert match.matched_by == ".ai-project.yaml"


def test_builtin_world_system_project_is_available_without_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path))

    projects = load_projects()
    match = detect_project(repo_path=str(code_root()))

    assert "world_system" in projects
    assert projects["world_system"]["repo"] == str(code_root())
    assert projects["world_system"]["test_commands"] == ["uv run pytest"]
    assert match.project_id == "world_system"
    assert match.needs_user is False


def test_builtin_world_system_does_not_override_user_registered_project(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    repo = str(code_root()).replace("\\", "\\\\")
    (home / "projects.yaml").write_text(
        f'projects:\n  custom_world:\n    project_id: custom_world\n    name: Custom World\n    repo: "{repo}"\n    test_commands: ["custom test"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))

    projects = load_projects()
    match = detect_project(repo_path=str(code_root()))

    assert "world_system" not in projects
    assert match.project_id == "custom_world"
