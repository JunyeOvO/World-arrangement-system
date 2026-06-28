from pathlib import Path

from orchestrator.project_registry import detect_project


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

