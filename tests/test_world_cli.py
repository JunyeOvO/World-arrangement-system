import json
import subprocess
from pathlib import Path

from orchestrator.cli import main


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=path, check=True)
    (path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_world_bootstrap_cli_outputs_json(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "ai-runtime"))

    code = main(["world-bootstrap", "--repo-path", str(repo)])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["world_enabled"] is True
    assert output["write_policy"] == "zero_write"
    assert output["project_id"] is None
    assert output["runtime_id"]
    assert Path(output["project_profile_path"]).exists()
    assert not (repo / ".world").exists()


def test_world_create_plan_cli_outputs_external_plan(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "ai-runtime"))

    code = main([
        "world-create-plan",
        "--repo-path",
        str(repo),
        "--goal",
        "Update README documentation",
        "--risk-level",
        "low",
    ])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["plan"]["route"]["selected_worker"] == "claude_code"
    assert Path(output["plan_path"]).exists()
    assert str(repo) not in output["plan_path"]
