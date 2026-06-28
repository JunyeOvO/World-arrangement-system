import subprocess
from pathlib import Path

import yaml

from orchestrator.scheduler import OrchestratorService


def _init_python_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=path, check=True)
    (path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_world_bootstrap_zero_write_keeps_repo_clean(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_python_repo(repo)
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "ai-runtime"))

    service = OrchestratorService()
    result = service.world_bootstrap(str(repo))

    assert result["world_enabled"] is True
    assert result["write_policy"] == "zero_write"
    assert result["runtime_backend"] == "external-global"
    assert result["project_id"] is None
    assert result["runtime_id"]
    assert result["detect"]["health"]["status"] == "unknown"
    assert Path(result["project_profile_path"]).exists()
    assert not (repo / ".world").exists()
    status = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, capture_output=True, check=True)
    assert status.stdout.strip() == ""


def test_world_create_plan_writes_external_plan(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_python_repo(repo)
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "ai-runtime"))

    service = OrchestratorService()
    result = service.world_create_plan(str(repo), "Update README documentation", "low")

    plan = result["plan"]
    assert plan["write_policy"] == "zero_write"
    assert plan["route"]["selected_worker"] == "claude_code"
    assert Path(result["plan_path"]).exists()
    assert str(repo) not in result["plan_path"]
    assert not (repo / ".world").exists()


def test_world_enabled_submit_task_uses_world_plan_route(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_python_repo(repo)
    runtime = tmp_path / "ai-runtime"
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world"))
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(runtime))
    runtime.mkdir()
    (runtime / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "projects": {
                    "demo": {
                        "repo": str(repo),
                        "stack": ["android", "python"],
                        "default_branch": "main",
                        "default_worker": "claude_code",
                        "default_model": "deepseek_pro",
                        "allow_auto_pr": False,
                        "allow_remote_push": False,
                        "world": {"enabled": True, "write_policy": "zero_write"},
                    }
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = OrchestratorService()
    result = service.submit_task(
        "demo",
        "World dry-run after registry refresh: analyze project state only, do not edit files",
        "low",
        dry_run=True,
    )
    route = service.artifacts.path(result["task_id"], "route.json")
    world_plan = service.artifacts.path(result["task_id"], "world_plan.json")

    route_payload = yaml.safe_load(route.read_text(encoding="utf-8"))
    plan_payload = yaml.safe_load(world_plan.read_text(encoding="utf-8"))
    assert route_payload == plan_payload["route"]
    assert route_payload["selected_worker"] == "claude_code"
    assert service.get_task_status(result["task_id"])["status"] == "DRY_RUN_COMPLETED"
    assert not (repo / ".world").exists()


def test_detect_project_reports_stale_registration_health(tmp_path, monkeypatch):
    runtime = tmp_path / "ai-runtime"
    runtime.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(runtime))
    missing_repo = tmp_path / "missing"
    requested_repo = tmp_path / "demo"
    requested_repo.mkdir()
    (runtime / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "projects": {
                    "demo": {
                        "project_id": "demo",
                        "name": "Demo",
                        "repo": str(missing_repo),
                        "allow_auto_pr": True,
                        "test_commands": [],
                        "build_commands": [],
                    }
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = OrchestratorService()
    result = service.detect_project(repo_path=str(requested_repo), git_remote_url="")

    assert result["project_id"] == "demo"
    assert result["matched_by"] == "fuzzy_name"
    assert result["health"]["status"] == "needs_fix"
    assert any("does not exist" in issue for issue in result["health"]["issues"])
    assert any("allow_auto_pr" in issue for issue in result["health"]["issues"])
