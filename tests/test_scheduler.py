"""Tests for scheduler retry chain and escalation logic."""
import json

from orchestrator.scheduler import (
    OrchestratorService,
    _apply_route_override,
    _build_retry_chain,
    _is_retryable_failure,
    _should_recover_failed_worker_diff,
    _skip_project_verification_for_read_only_task,
    _task_requires_diff,
    _task_requests_project_verification,
    _worker_prompt,
)


class _FakeResult:
    def __init__(self, status):
        self.status = status


def test_build_retry_chain_default():
    """Default route should produce a single-attempt chain."""
    route = {"selected_worker": "claude_code", "selected_model": "deepseek_pro"}
    chain = _build_retry_chain(route, {})
    assert len(chain) == 1
    assert chain[0]["worker"] == "claude_code"
    assert chain[0]["model"] == "deepseek_pro"


def test_build_retry_chain_with_opencode_escalation():
    """Route with opencode_on_failure should add OpenCode escalation."""
    route = {
        "selected_worker": "claude_code", "selected_model": "deepseek_pro",
        "escalation_policy": "opencode_on_failure",
        "fallback_models": [],
    }
    chain = _build_retry_chain(route, {})
    assert len(chain) >= 3  # primary + opencode high + opencode max
    workers = [a["worker"] for a in chain]
    assert "claude_code" in workers
    assert "opencode" in workers
    opencode_attempts = [a for a in chain if a["worker"] == "opencode"]
    assert len(opencode_attempts) >= 2


def test_build_retry_chain_with_dict_fallbacks():
    """Fallback models as dicts should be parsed into chain entries."""
    route = {
        "selected_worker": "claude_code", "selected_model": "deepseek_pro",
        "fallback_models": [
            {"worker": "opencode", "model": "opencode_go_glm52", "variant": "high",
             "reason": "escalation after claude failure"},
        ],
    }
    chain = _build_retry_chain(route, {})
    assert len(chain) == 2
    assert chain[1]["worker"] == "opencode"
    assert chain[1]["model"] == "opencode_go_glm52"
    assert chain[1]["variant"] == "high"


def test_build_retry_chain_prefers_route_retry_chain():
    route = {
        "selected_worker": "claude_code",
        "selected_model": "deepseek_pro",
        "fallback_models": ["opencode-go/glm-5.2"],
        "retry_chain": [
            {"worker": "claude_code", "model": "deepseek_pro", "intensity": "medium"},
            {"worker": "opencode", "model": "opencode-go/glm-5.2", "variant": "high", "intensity": "high"},
        ],
    }

    chain = _build_retry_chain(route, {})

    assert len(chain) == 2
    assert chain[1]["worker"] == "opencode"
    assert chain[1]["model"] == "opencode-go/glm-5.2"
    assert chain[1]["variant"] == "high"


def test_route_override_forces_single_opencode_attempt():
    route = {
        "selected_worker": "claude_code",
        "selected_model": "deepseek_pro",
        "variant": None,
        "fallback_models": ["opencode-go/glm-5.2"],
        "retry_chain": [{"worker": "claude_code", "model": "deepseek_pro"}],
    }
    task = {
        "route_override": {
            "worker": "opencode",
            "model": "opencode-go/glm-5.2",
            "variant": "high",
        }
    }

    overridden = _apply_route_override(route, task)
    chain = _build_retry_chain(overridden, task)

    assert overridden["selected_worker"] == "opencode"
    assert overridden["selected_model"] == "opencode-go/glm-5.2"
    assert overridden["agent_llm"] == "opencode + GLM 5.2"
    assert len(chain) == 1
    assert chain[0]["worker"] == "opencode"
    assert chain[0]["variant"] == "high"


def test_claude_failure_escalates_to_opencode_glm52():
    """Hotpatch: escalation chain should include OpenCode after ClaudeCodeWorker."""
    route = {
        "selected_worker": "claude_code", "selected_model": "deepseek_pro",
        "escalation_policy": "opencode_on_failure",
    }
    chain = _build_retry_chain(route, {})
    assert chain[0]["worker"] == "claude_code"
    opencode_in_chain = any(a["worker"] == "opencode" and "glm" in a["model"].lower() for a in chain)
    assert opencode_in_chain, "Expected OpenCode + GLM-5.2 in escalation chain"


def test_is_retryable_failure():
    """Worker failures should be retryable; blocked/safety should not."""
    assert _is_retryable_failure(_FakeResult("failed"))
    assert _is_retryable_failure(_FakeResult("worker_failed"))
    assert not _is_retryable_failure(_FakeResult("blocked"))
    assert not _is_retryable_failure(_FakeResult("cancelled"))
    assert not _is_retryable_failure(_FakeResult("dangerous_command"))
    assert not _is_retryable_failure(_FakeResult("forbidden_path"))


def test_should_recover_failed_worker_diff_only_for_failed_with_changes():
    class Result:
        def __init__(self, status, changed_files):
            self.status = status
            self.changed_files = changed_files

    assert _should_recover_failed_worker_diff(Result("failed", ["app.py"]))
    assert not _should_recover_failed_worker_diff(Result("failed", []))
    assert not _should_recover_failed_worker_diff(Result("blocked", ["app.py"]))
    assert not _should_recover_failed_worker_diff(Result("success", ["app.py"]))


def test_verify_gate_requires_build_passed():
    from pathlib import Path

    source = Path("orchestrator/scheduler.py").read_text(encoding="utf-8")

    assert "not verify_result.build_passed" in source


def test_edit_task_requires_diff():
    assert _task_requires_diff({"user_goal": "Find one bug and fix it", "task_type": "simple_bugfix"})
    assert not _task_requires_diff({"user_goal": "Analyze the repo", "task_type": "analysis"})
    assert not _task_requires_diff({"user_goal": "Find one bug and fix it", "allow_empty_diff": True})
    assert not _task_requires_diff({
        "user_goal": "目标：简单评价 Travel_with_me 项目质量。约束：只做只读分析，不修改文件，返回项目质量评价。",
    })
    assert _task_requires_diff({"user_goal": "先分析根因，然后修复登录 bug"})


def test_read_only_task_skips_project_verification_without_explicit_request():
    class Result:
        changed_files: list[str] = []

    task = {
        "user_goal": "目标：简单评价 Travel_with_me 项目质量。约束：只做只读分析，不修改文件，返回项目质量评价。",
    }

    assert not _task_requests_project_verification(task)
    assert _skip_project_verification_for_read_only_task(task, Result())


def test_verifiable_path_wording_does_not_force_project_verification():
    task = {
        "user_goal": "简单评价项目质量，按任务性质选择最小可验证路径，只做只读分析，不修改文件。",
    }

    assert not _task_requests_project_verification(task)


def test_explicit_test_request_does_not_skip_project_verification():
    class Result:
        changed_files: list[str] = []

    task = {"user_goal": "Analyze the repo and run npm test"}

    assert _task_requests_project_verification(task)
    assert not _skip_project_verification_for_read_only_task(task, Result())


def test_opencode_prompt_embeds_context_without_external_artifact_paths(tmp_path):
    task = {
        "user_goal": "Fix one bug",
        "run_dir": str(tmp_path / "run"),
        "worktree_path": str(tmp_path / "worktree"),
        "risk_level": "medium",
        "forbidden_paths": [".env"],
    }

    prompt = _worker_prompt(task, {"selected_worker": "opencode", "selected_model": "opencode-go/glm-5.2"})

    assert "Fix one bug" in prompt
    assert "Do not read run artifacts outside the worktree" in prompt
    assert "Test commands:" in prompt
    assert "Build commands:" in prompt
    assert "Task JSON:" not in prompt
    assert "Route JSON:" not in prompt


def test_get_task_control_reads_control_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    run_dir = tmp_path / "run"
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True)
    (control_dir / "process.json").write_text(
        json.dumps({"pid": 123, "status": "running"}), encoding="utf-8"
    )
    (control_dir / "heartbeat.json").write_text(
        json.dumps({"status": "running", "elapsed_sec": 1.2}), encoding="utf-8"
    )
    service.db.create_task({
        "task_id": "t_control",
        "project_id": "p",
        "repo_path": str(tmp_path),
        "user_goal": "test",
        "status": "EXECUTING",
        "created_at": "now",
        "updated_at": "now",
        "route_worker": "opencode",
        "route_model": "opencode-go/glm-5.2",
        "route_variant": "high",
        "pr_url": None,
        "run_dir": str(run_dir),
    })

    result = service.get_task_control("t_control")

    assert result["task_status"] == "EXECUTING"
    assert result["process"]["pid"] == 123
    assert result["heartbeat"]["status"] == "running"


def test_scheduler_writes_verify_and_metrics_artifacts(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    home = tmp_path / "home"
    home.mkdir()
    (home / "models.yaml").write_text(
        "models:\n  deepseek_pro:\n    provider: deepseek\n    adapter: claude_code\n"
        "    model: deepseek-v4-pro\n    worker: claude_code\n",
        encoding="utf-8",
    )
    (home / "policies.yaml").write_text(
        Path("config/policies.yaml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (home / "projects.yaml").write_text(
        "projects:\n  generic:\n    project_id: generic\n    name: Generic\n"
        f"    repo: {repo}\n    stack: [python]\n    test_commands: []\n    build_commands: []\n"
        "    forbidden_paths: []\n    default_worker: claude_code\n"
        "    default_model: deepseek_pro\n    allow_auto_pr: false\n    allow_remote_push: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    monkeypatch.setattr("orchestrator.scheduler._task_requires_diff", lambda task: False)

    service = OrchestratorService()
    result = service.submit_task("generic", "analyze repository", "low", True, False, dry_run=True)
    run_dir = Path(result["run_dir"])

    assert service.get_task_status(result["task_id"])["status"] == "COMPLETED_WITH_PATCH"
    verify_payload = json.loads((run_dir / "verify" / "verify.json").read_text(encoding="utf-8"))
    metrics_payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    db_metrics = service.db.list_task_metrics(result["task_id"])

    assert verify_payload["tests_passed"] is True
    assert verify_payload["build_passed"] is True
    assert verify_payload["forbidden_allowed"] is True
    assert metrics_payload["task_id"] == result["task_id"]
    assert db_metrics[0]["model"] == "deepseek_pro"


def test_scheduler_permission_diff_check_writes_audit_event(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    service.db.create_task({
        "task_id": "t_perm",
        "project_id": "p",
        "repo_path": str(tmp_path),
        "user_goal": "test",
        "status": "EXECUTING",
        "created_at": "now",
        "updated_at": "now",
        "route_worker": "claude_code",
        "route_model": "deepseek_pro",
        "route_variant": "",
        "pr_url": None,
        "run_dir": str(tmp_path / "run"),
    })

    review = service._check_worker_diff_permissions("t_perm", "claude_code", [".env"])
    events = service.db.list_events("t_perm")

    assert review["allowed"] is False
    assert events[-1]["event_type"] == "permission_denied"
    payload = json.loads(events[-1]["payload_json"])
    assert payload["permission"]["denied"][0]["target"] == ".env"


def test_scheduler_permission_preflight_requires_approval_for_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    service.db.create_task({
        "task_id": "t_prod",
        "project_id": "p",
        "repo_path": str(tmp_path),
        "user_goal": "test",
        "status": "EXECUTING",
        "created_at": "now",
        "updated_at": "now",
        "route_worker": "opencode",
        "route_model": "opencode-go/glm-5.2",
        "route_variant": "high",
        "pr_url": None,
        "run_dir": str(tmp_path / "run"),
    })

    review = service._check_worker_declared_permissions(
        "t_prod",
        "opencode",
        {"target_paths": ["infra/prod/main.tf"]},
    )

    assert review["allowed"] is True
    assert review["requires_ask"] is True
    assert service.db.list_events("t_prod")[-1]["event_type"] == "permission_preflight"
