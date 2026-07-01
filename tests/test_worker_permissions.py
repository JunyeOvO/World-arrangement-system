"""Phase 6 tests: Static Worker Permission Profiles."""
import pytest
import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

from orchestrator.db import TaskDB
from orchestrator.permissions import (
    load_permissions,
    check_write_path,
    check_write_paths,
    check_bash_command,
    check_worker_launch_command,
    check_provider,
    WorkerPermissions,
)
from orchestrator.worker_permission_audit import WorkerPermissionAuditor, declared_write_paths


# ── Load profiles ──

def test_claude_worker_uses_standard_safe_profile():
    wp = load_permissions("claude_code")
    assert wp.profile == "standard_safe"
    assert wp.timeout_sec == 300
    assert wp.effort_default == "medium"


def test_opencode_worker_uses_advanced_code_safe_profile():
    wp = load_permissions("opencode")
    assert wp.profile == "advanced_code_safe"
    assert wp.timeout_sec == 600


# ── Provider checks ──

def test_claude_worker_allows_deepseek():
    result = check_provider("claude_code", "deepseek_pro")
    assert result.allowed


def test_claude_worker_allows_mimo():
    result = check_provider("claude_code", "mimo_v25_pro")
    assert result.allowed


def test_claude_worker_denies_glm():
    result = check_provider("claude_code", "opencode-go/glm-5.2")
    assert not result.allowed


def test_claude_worker_denies_z_ai():
    result = check_provider("claude_code", "z_ai_pro")
    assert not result.allowed


# ── Write path checks ──

def test_write_src_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "src/login.tsx")
        assert result.allowed, f"{name} should allow src/**"


def test_write_env_is_denied():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, ".env")
        assert not result.allowed, f"{name} should deny .env"


def test_write_secrets_is_denied():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "secrets/stripe-key.json")
        assert not result.allowed, f"{name} should deny secrets/**"


def test_write_pem_is_denied():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "certs/server.pem")
        assert not result.allowed, f"{name} should deny *.pem"


def test_write_prod_infra_requires_ask():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "infra/prod/terraform/main.tf")
        assert result.allowed and result.requires_ask, f"{name} should ask for infra/prod/**"


def test_write_package_json_requires_ask():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "package.json")
        assert result.allowed and result.requires_ask, f"{name} should ask for package.json"


def test_write_pyproject_toml_requires_ask():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "pyproject.toml")
        assert result.allowed and result.requires_ask, f"{name} should ask for pyproject.toml"


def test_write_dockerfile_requires_ask():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "Dockerfile")
        assert result.allowed and result.requires_ask, f"{name} should ask for Dockerfile"


def test_write_readme_allowed_no_ask():
    for name in ["claude_code", "opencode"]:
        result = check_write_path(name, "README.md")
        assert result.allowed and not result.requires_ask, f"{name} should allow README.md"


# ── Bash command checks ──

def test_git_status_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "git status")
        assert result.allowed, f"{name} should allow git status"


def test_git_push_denied():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "git push origin main")
        assert not result.allowed, f"{name} should deny git push"


def test_git_merge_denied():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "git merge feature-branch")
        assert not result.allowed, f"{name} should deny git merge"


def test_rm_rf_denied():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "rm -rf /")
        assert not result.allowed, f"{name} should deny rm -rf /"


def test_dangerously_skip_permissions_denied():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "claude --dangerously-skip-permissions")
        assert not result.allowed, f"{name} should deny --dangerously-skip-permissions"


def test_pytest_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "pytest tests/ -v")
        assert result.allowed, f"{name} should allow pytest"


def test_npm_test_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "npm test")
        assert result.allowed, f"{name} should allow npm test"


def test_windows_npm_cmd_test_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "npm.cmd test")
        assert result.allowed, f"{name} should allow npm.cmd test"


def test_uv_pytest_allowed():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "uv run pytest tests/test_verifier.py")
        assert result.allowed, f"{name} should allow uv run pytest"


def test_bash_command_rejects_allow_prefix_without_word_boundary():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "pytestmalicious tests")
        assert not result.allowed, f"{name} should reject pytest prefix smuggling"


def test_bash_command_rejects_shell_control_operators():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "pytest tests && git status")
        assert not result.allowed, f"{name} should reject chained shell commands"


def test_bash_command_rejects_denied_command_after_allowed_prefix():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "pytest tests; rm -rf /")
        assert not result.allowed, f"{name} should reject denied command after separator"


def test_npm_install_requires_ask():
    for name in ["claude_code", "opencode"]:
        result = check_bash_command(name, "npm install react")
        assert result.allowed and result.requires_ask, f"{name} should ask for npm install"


# ── Both workers share same danger boundaries ──

def test_both_workers_forbid_push_merge():
    """Both workers must forbid git push and git merge."""
    for name in ["claude_code", "opencode"]:
        assert not check_bash_command(name, "git push origin main").allowed
        assert not check_bash_command(name, "git merge feature").allowed


def test_both_workers_forbid_secret_paths():
    """Both workers must forbid writes to secret paths."""
    secret_paths = [".env", "secrets/token", "keys/private.pem", "credentials.json"]
    for name in ["claude_code", "opencode"]:
        for path in secret_paths:
            result = check_write_path(name, path)
            assert not result.allowed, f"{name} must deny {path}"


def test_opencode_worker_does_not_allow_dangerous_bypass():
    """OpenCodeWorker must not use --dangerously-skip-permissions."""
    result = check_bash_command("opencode", "claude --dangerously-skip-permissions run")
    assert not result.allowed


def test_worker_permissions_config_matches_schema():
    schema = json.loads(Path("schemas/worker_permissions.schema.json").read_text(encoding="utf-8"))
    config = yaml.safe_load(Path("config/worker_permissions.yaml").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(config)


def test_bulk_write_review_reports_denied_and_ask():
    review = check_write_paths("claude_code", ["src/app.py", "infra/prod/main.tf", ".env"])

    assert review.allowed is False
    assert review.requires_ask is True
    assert any(check.target == ".env" and not check.allowed for check in review.checks)
    assert any(check.target == "infra/prod/main.tf" and check.requires_ask for check in review.checks)


def test_worker_permission_auditor_records_preflight_and_diff_events(tmp_path):
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": "t_perm",
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "edit infra",
            "status": "EXECUTING",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(tmp_path / "run"),
        }
    )
    auditor = WorkerPermissionAuditor(db)

    preflight = auditor.check_declared_permissions(
        "t_perm",
        "claude_code",
        {
            "owned_paths": ["src/app.py", "src/app.py"],
            "target_paths": ["infra/prod/main.tf"],
            "planned_files": [".env"],
        },
    )
    diff = auditor.check_diff_permissions("t_perm", "claude_code", ["src/app.py"])
    events = db.list_events("t_perm")

    assert declared_write_paths(
        {"owned_paths": ["a"], "target_paths": ["a", "b"], "planned_files": ["c"]}
    ) == ["a", "b", "c"]
    assert not preflight["allowed"]
    assert preflight["requires_ask"]
    assert diff["allowed"]
    assert events[-2]["event_type"] == "permission_preflight"
    assert events[-1]["event_type"] == "permission_diff_checked"


def test_worker_launch_command_checks_deny_list_only():
    allowed = check_worker_launch_command("opencode", "opencode run -m opencode-go/glm-5.2")
    denied = check_worker_launch_command("opencode", "opencode run --dangerously-skip-permissions")
    chained = check_worker_launch_command("opencode", "opencode run -m opencode-go/glm-5.2; git push")

    assert allowed.allowed
    assert not denied.allowed
    assert not chained.allowed
