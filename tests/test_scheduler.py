"""Tests for scheduler retry chain and escalation logic."""
import json

from orchestrator.scheduler import (
    OrchestratorService,
    _apply_route_override,
    _build_retry_chain,
    _is_retryable_failure,
    _should_recover_failed_worker_diff,
    _task_requires_diff,
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
