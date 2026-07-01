import json
import subprocess
from pathlib import Path

import yaml

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


def test_submit_task_cli_writes_explicit_protocol(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    runtime = tmp_path / "ai-runtime"
    runtime.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(runtime))
    (runtime / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "projects": {
                    "demo": {
                        "repo": str(repo),
                        "default_branch": "main",
                        "test_commands": ["npm test", "npm run check"],
                        "build_commands": ["npm run build"],
                        "forbidden_paths": [".env"],
                        "allow_auto_pr": False,
                    }
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    code = main([
        "submit-task",
        "--project",
        "demo",
        "--goal",
        "Find one bug and output a fix plan only",
        "--no-execute",
        "--task-mode",
        "read_only",
        "--expected-diff",
        "false",
        "--verification-policy",
        "changed_files_only",
        "--read-budget-profile",
        "code_contract_audit",
        "--read-budget",
        "max_files=5",
        "--read-budget",
        "max_worker_turns=4",
    ])
    output = json.loads(capsys.readouterr().out)
    task = json.loads((Path(output["run_dir"]) / "task.json").read_text(encoding="utf-8"))

    assert code == 0
    assert task["task_mode"] == "read_only"
    assert task["expected_diff"] is False
    assert task["verification_policy"] == "changed_files_only"
    assert task["read_budget_profile"] == "code_contract_audit"
    assert task["read_budget"]["max_files"] == 5
    assert task["read_budget"]["max_worker_turns"] == 4
    assert task["read_budget"]["max_duration_sec"] == 150


def test_submit_current_project_task_cli_detects_project_and_preserves_route(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    runtime = tmp_path / "ai-runtime"
    runtime.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(runtime))
    (runtime / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "projects": {
                    "demo": {
                        "repo": str(repo),
                        "default_branch": "main",
                        "test_commands": ["npm test"],
                        "build_commands": [],
                        "forbidden_paths": [".env"],
                        "allow_auto_pr": False,
                    }
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    code = main([
        "submit-current-project-task",
        "--repo-path",
        str(repo),
        "--goal",
        "Inspect one file only",
        "--no-execute",
        "--dry-run",
        "--worker",
        "opencode",
        "--model",
        "opencode_go_glm52",
        "--variant",
        "high",
        "--task-mode",
        "read_only",
        "--expected-diff",
        "false",
        "--verification-policy",
        "changed_files_only",
        "--read-budget-profile",
        "quick_triage",
        "--read-budget",
        "max_files=3",
    ])
    output = json.loads(capsys.readouterr().out)
    task = json.loads((Path(output["run_dir"]) / "task.json").read_text(encoding="utf-8"))

    assert code == 0
    assert output["status"] == "QUEUED"
    assert task["project_id"] == "demo"
    assert task["route_override"] == {
        "worker": "opencode",
        "model": "opencode_go_glm52",
        "variant": "high",
    }
    assert task["task_mode"] == "read_only"
    assert task["expected_diff"] is False
    assert task["verification_policy"] == "changed_files_only"
    assert task["read_budget_profile"] == "quick_triage"
    assert task["read_budget"]["max_files"] == 3
