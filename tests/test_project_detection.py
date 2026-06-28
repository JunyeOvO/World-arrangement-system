"""Tests for project detection from global projects.yaml."""
import tempfile
import os
from pathlib import Path

from orchestrator.project_registry import detect_project


def test_detect_project_from_global_projects_yaml():
    """Hotpatch: detect project from global projects.yaml by repo path."""
    # Create temp projects.yaml
    tmp = Path(tempfile.mkdtemp())
    projects_yaml = tmp / "projects.yaml"
    repo_path = str(tmp / "myproject")
    os.makedirs(repo_path, exist_ok=True)

    # Use forward slashes for YAML safety on Windows
    safe_repo = repo_path.replace("\\", "/")
    projects_yaml.write_text(f"""
projects:
  test_project:
    project_id: "test_project"
    name: "Test Project"
    repo: "{safe_repo}"
    default_branch: "main"
    pr_base_branch: "main"
    stack: ["python"]
    test_commands: []
    build_commands: []
    forbidden_paths: [".env"]
    default_worker: "claude_code"
    default_model: "deepseek_pro"
    allow_auto_pr: false
    allow_remote_push: false
""", encoding="utf-8")

    # Override home to use our temp projects.yaml
    old_home = os.environ.get("AI_ORCHESTRATOR_HOME")
    os.environ["AI_ORCHESTRATOR_HOME"] = str(tmp)

    try:
        match = detect_project(repo_path=repo_path)
        assert match.project_id == "test_project", f"Expected test_project, got {match.project_id}"
        assert match.matched_by == "repo_path"
        assert match.confidence >= 0.8
    finally:
        if old_home:
            os.environ["AI_ORCHESTRATOR_HOME"] = old_home
        else:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_detect_project_needs_user_for_unknown():
    """Unrecognized project should return needs_user=True."""
    match = detect_project(repo_path="/nonexistent/path/12345")
    assert match.needs_user or match.project_id is None
