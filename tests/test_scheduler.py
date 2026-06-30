"""Tests for scheduler retry chain and escalation logic."""
import json
import subprocess
from pathlib import Path

from orchestrator.scheduler import (
    OrchestratorService,
    _worker_prompt,
)
from orchestrator.failure_classifier import FailureClassification
from orchestrator.read_only_completion import (
    read_only_failure_summary as _read_only_failure_summary,
    skip_project_verification_for_read_only_task as _skip_project_verification_for_read_only_task,
    task_requires_diff as _task_requires_diff,
    task_requests_project_verification as _task_requests_project_verification,
)
from orchestrator.task_routing import (
    apply_route_override as _apply_route_override,
    world_enabled,
    world_write_policy,
)
from orchestrator.worker_attempts import (
    build_retry_chain as _build_retry_chain,
    is_retryable_failure as _is_retryable_failure,
    should_recover_failed_worker_diff as _should_recover_failed_worker_diff,
)
from orchestrator.workers.base import WorkerResult


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


def test_world_route_policy_supports_new_and_legacy_project_flags():
    assert world_enabled({"world": {"enabled": True}})
    assert world_enabled({"world_enabled": True})
    assert not world_enabled({})
    assert world_write_policy({"world": {"write_policy": "zero_write"}}) == "zero_write"
    assert world_write_policy({"world_write_policy": "sandbox_only"}) == "sandbox_only"
    assert world_write_policy({}) == "zero_write"


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

    source = Path("orchestrator/task_verification.py").read_text(encoding="utf-8")

    assert "not verify_result.build_passed" in source


def test_edit_task_requires_diff():
    assert _task_requires_diff({"user_goal": "Find one bug and fix it", "task_type": "simple_bugfix"})
    assert not _task_requires_diff({"user_goal": "Analyze the repo", "task_type": "analysis"})
    assert not _task_requires_diff({"user_goal": "Find one bug and fix it", "allow_empty_diff": True})
    assert not _task_requires_diff({"user_goal": "Find one bug and fix it", "expected_diff": False})
    assert not _task_requires_diff({"user_goal": "Find one bug and fix it", "task_mode": "read_only"})
    assert not _task_requires_diff({
        "user_goal": "目标：简单评价 Travel_with_me 项目质量。约束：只做只读分析，不修改文件，返回项目质量评价。",
    })
    assert _task_requires_diff({"user_goal": "先分析根因，然后修复登录 bug"})


def test_explicit_read_only_instruction_overrides_fix_plan_wording():
    assert not _task_requires_diff({
        "user_goal": (
            "只读调查 travel_with_me 的语言和框架，不修改文件。"
            "输出问题、风险、修复计划和下一步建议。"
        ),
        "task_type": "analysis",
    })


def test_read_only_task_skips_project_verification_without_explicit_request():
    class Result:
        changed_files: list[str] = []

    task = {
        "user_goal": "目标：简单评价 Travel_with_me 项目质量。约束：只做只读分析，不修改文件，返回项目质量评价。",
    }

    assert not _task_requests_project_verification(task)
    assert _skip_project_verification_for_read_only_task(task, Result())


def test_explicit_unit_policy_overrides_read_only_skip():
    class Result:
        changed_files: list[str] = []

    task = {
        "user_goal": "只读分析项目质量",
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "unit",
    }

    assert not _skip_project_verification_for_read_only_task(task, Result())


def test_read_only_max_turns_with_text_can_finish_without_fallback(tmp_path):
    stream = tmp_path / "worker.jsonl"
    stream.write_text(
        json.dumps({"type": "result", "subtype": "success", "result": "Read-only audit completed."}) + "\n",
        encoding="utf-8",
    )
    result = WorkerResult(
        status="failed",
        summary="Claude Code worker failed",
        changed_files=[],
        stdout_path=str(stream),
    )
    failure = FailureClassification(
        "max_turns_no_diff",
        True,
        "escalate_model_or_narrow_task",
    )

    summary = _read_only_failure_summary(
        {"user_goal": "只读分析项目质量，不修改文件。", "task_type": "analysis"},
        result,
        failure,
    )

    assert summary == "Partial read-only result salvaged after worker budget limit.\n\nRead-only audit completed."


def test_read_only_max_turns_with_partial_text_can_be_salvaged(tmp_path):
    stream = tmp_path / "worker.jsonl"
    partial = (
        "## Summary\n\n"
        "This read-only planning pass found three next candidates: tighten task status mapping, "
        "add dashboard regression tests, and document the execution protocol. Risks are limited "
        "because changed_files=[] and no project files were modified.\n\n"
        "Next step: choose one bounded patch task."
    )
    stream.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": partial}]}}) + "\n",
        encoding="utf-8",
    )
    result = WorkerResult(
        status="failed",
        summary="Claude Code worker failed",
        changed_files=[],
        stdout_path=str(stream),
    )
    failure = FailureClassification("max_turns_no_diff", True, "escalate_model_or_narrow_task")

    summary = _read_only_failure_summary(
        {"user_goal": "挑选下一轮 World 小修候选任务，只读，不修改文件。", "task_mode": "read_only", "expected_diff": False},
        result,
        failure,
    )

    assert summary is not None
    assert summary.startswith("Partial read-only result salvaged")
    assert "three next candidates" in summary
    assert result.partial_result is True


def test_read_only_max_turns_with_stream_delta_can_be_salvaged(tmp_path):
    stream = tmp_path / "worker.jsonl"
    stream.write_text(
        "\n".join([
            json.dumps({"type": "content_block_delta", "delta": {"text": "## Summary\n\n"}}),
            json.dumps({"type": "content_block_delta", "delta": {"text": "This partial read-only result includes risks, recommendations, and next steps. "}}),
            json.dumps({"type": "content_block_delta", "delta": {"text": "No files were changed and changed_files=[] remains empty."}}),
        ]) + "\n",
        encoding="utf-8",
    )
    result = WorkerResult(
        status="failed",
        summary="Claude Code worker failed",
        changed_files=[],
        stdout_path=str(stream),
    )

    summary = _read_only_failure_summary(
        {"user_goal": "只读分析项目质量，不修改文件。", "task_mode": "read_only", "expected_diff": False},
        result,
        FailureClassification("max_turns_no_diff", True, "escalate_model_or_narrow_task"),
    )

    assert summary is not None
    assert "partial read-only result" in summary
    assert result.partial_result is True


def test_verifiable_path_wording_does_not_force_project_verification():
    task = {
        "user_goal": "简单评价项目质量，按任务性质选择最小可验证路径，只做只读分析，不修改文件。",
    }

    assert not _task_requests_project_verification(task)


def test_read_only_test_command_recommendation_does_not_force_project_verification():
    task = {
        "user_goal": "只读判断技术栈和测试命令是否适合 MVP 评估。限定只读文件：package.json、vitest.config.js、playwright.config.js。验收标准：输出最小测试命令，例如 npm test；changed_files=[]。",
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
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget_profile": "code_contract_audit",
        "read_budget": {"max_files": 5, "max_worker_turns": 4},
        "project_memory": {"prompt": "\n## Project Memory\n- README.md: app overview\n"},
    }

    prompt = _worker_prompt(task, {"selected_worker": "opencode", "selected_model": "opencode-go/glm-5.2"})

    assert "Fix one bug" in prompt
    assert "Do not read run artifacts outside the worktree" in prompt
    assert "Test commands:" in prompt
    assert "Build commands:" in prompt
    assert "Task mode: read_only" in prompt
    assert "Expected diff: false" in prompt
    assert "Verification policy: changed_files_only" in prompt
    assert "Read budget profile: code_contract_audit" in prompt
    assert '"max_files": 5' in prompt
    assert "Read-only completion rule:" in prompt
    assert "Required read-only output contract:" in prompt
    assert "do not spend the final allowed turn on another Read/List/Search" in prompt
    assert "status: success" in prompt
    assert "changed_files: []" in prompt
    assert "## Project Memory" in prompt
    assert "README.md: app overview" in prompt
    assert "Task JSON:" not in prompt
    assert "Route JSON:" not in prompt


def test_next_task_planning_prompt_limits_search_and_requires_early_draft(tmp_path):
    worktree = tmp_path / "worktree"
    (worktree / "js").mkdir(parents=True)
    (worktree / "tests").mkdir()
    (worktree / "README.md").write_text("# Travel With Me\n", encoding="utf-8")
    (worktree / "js" / "main.js").write_text(
        "export function boot() {}\nconst staleCandidate = true;\nconst API_KEY = 'sk-thismustberedacted123456';\n",
        encoding="utf-8",
    )
    (worktree / "js" / "bundle.js").write_text("x" * 300_000, encoding="utf-8")
    (worktree / "tests" / "main.test.js").write_text("test('x', () => {})\n", encoding="utf-8")
    task = {
        "user_goal": "挑选下一轮 World 小修候选任务，只读，不修改文件。",
        "run_dir": str(tmp_path / "run"),
        "worktree_path": str(worktree),
        "risk_level": "low",
        "forbidden_paths": [".env"],
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget_profile": "next_task_planning",
        "read_budget": {"max_files": 14, "max_dirs": 5, "max_worker_turns": 14},
    }

    prompt = _worker_prompt(task, {"selected_worker": "claude_code", "selected_model": "deepseek_flash"})

    assert "Next-task planning strategy:" in prompt
    assert "Do not use Agent/subagent tools" in prompt
    assert "Do not run shell commands" in prompt
    assert "Read at most 3 additional files total" in prompt
    assert "After the first plausible next task candidate is identified" in prompt
    assert "one high-confidence candidate is better than timing out" in prompt
    assert "Seed files World already selected" in prompt
    assert "Seed evidence excerpts" in prompt
    assert "- README.md" in prompt
    assert "- js/main.js" in prompt
    assert "export function boot() {}" in prompt
    assert "const staleCandidate = true;" in prompt
    assert "API_KEY=[REDACTED]" in prompt
    assert "sk-thismustberedacted" not in prompt
    assert "bundle.js" not in prompt


def test_code_contract_profile_gets_early_output_strategy_not_next_task_seed(tmp_path):
    worktree = tmp_path / "worktree"
    (worktree / "js").mkdir(parents=True)
    (worktree / "tests").mkdir()
    (worktree / "js" / "three-work-area.js").write_text(
        "export function resolveAnchored3DWorkArea(workArea) { return workArea?.bounds; }\n",
        encoding="utf-8",
    )
    (worktree / "js" / "state.js").write_text("export const selectedWorkArea = null;\n", encoding="utf-8")
    (worktree / "tests" / "work-area.test.js").write_text("test('work area', () => {})\n", encoding="utf-8")
    task = {
        "user_goal": "只读调查 3D workArea 数据契约风险",
        "run_dir": str(tmp_path / "run"),
        "worktree_path": str(worktree),
        "risk_level": "low",
        "forbidden_paths": [".env"],
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget_profile": "code_contract_audit",
        "read_budget": {"max_files": 10, "max_worker_turns": 10},
    }

    prompt = _worker_prompt(task, {"selected_worker": "claude_code", "selected_model": "deepseek_flash"})

    assert "Next-task planning strategy:" not in prompt
    assert "Seed files World selected for code_contract_audit" in prompt
    assert "Seed evidence excerpts" in prompt
    assert "- js/three-work-area.js" in prompt
    assert "resolveAnchored3DWorkArea" in prompt
    assert "Code-contract audit early-output strategy:" in prompt
    assert "Required read-only output contract:" in prompt
    assert "Read at most 3 files before drafting a contract hypothesis" in prompt
    assert "producer, consumer, mismatch risk" in prompt
    assert "suspected_contract:" in prompt
    assert "If you think 'I have enough data', immediately return the template" in prompt


def test_quick_triage_and_docs_review_profiles_get_early_output_strategy(tmp_path):
    worktree = tmp_path / "worktree"
    (worktree / "js").mkdir(parents=True)
    (worktree / "README.md").write_text("# Travel With Me\n", encoding="utf-8")
    (worktree / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (worktree / "js" / "main.js").write_text("export function boot() {}\n", encoding="utf-8")
    base_task = {
        "user_goal": "只读调查项目状态，不修改文件。",
        "run_dir": str(tmp_path / "run"),
        "worktree_path": str(worktree),
        "risk_level": "low",
        "forbidden_paths": [".env"],
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget": {"max_files": 6, "max_worker_turns": 6},
    }

    quick_prompt = _worker_prompt(
        {**base_task, "read_budget_profile": "quick_triage"},
        {"selected_worker": "claude_code", "selected_model": "deepseek_flash"},
    )
    docs_prompt = _worker_prompt(
        {**base_task, "read_budget_profile": "docs_review"},
        {"selected_worker": "claude_code", "selected_model": "deepseek_flash"},
    )

    assert "Quick-triage early-output strategy:" in quick_prompt
    assert "Seed files World selected for quick_triage" in quick_prompt
    assert "- README.md" in quick_prompt
    assert "- package.json" in quick_prompt
    assert "Travel With Me" in quick_prompt
    assert "Required read-only output contract:" in quick_prompt
    assert "Read at most 2 files before drafting a provisional result" in quick_prompt
    assert "conclusion:" in quick_prompt
    assert "Docs-review early-output strategy:" in docs_prompt
    assert "Required read-only output contract:" in docs_prompt
    assert "Read at most 2 docs or config files before drafting a scorecard" in docs_prompt
    assert "scorecard:" in docs_prompt


def test_get_task_control_reads_control_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    run_dir = service.artifacts.run_dir("t_reap")
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

    assert service.get_task_status(result["task_id"])["status"] == "DRY_RUN_COMPLETED"
    verify_payload = json.loads((run_dir / "verify" / "verify.json").read_text(encoding="utf-8"))
    review_payload = json.loads((run_dir / "review" / "review.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")
    metrics_payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    ledger_payload = json.loads((run_dir / "token_ledger.json").read_text(encoding="utf-8"))
    db_metrics = service.db.list_task_metrics(result["task_id"])

    assert verify_payload["tests_passed"] is True
    assert verify_payload["build_passed"] is True
    assert verify_payload["forbidden_allowed"] is True
    assert review_payload["review_mode"] == "degraded_mock"
    assert review_payload["approved"] is False
    assert review_payload["can_create_pr"] is False
    assert "degraded_mock_result" in final_md
    assert metrics_payload["task_id"] == result["task_id"]
    assert db_metrics[0]["model"] == "deepseek_pro"
    assert ledger_payload["task_id"] == result["task_id"]
    assert ledger_payload["codex"]["event_count"] >= 1
    assert ledger_payload["worker"]["attempts"] == 1
    assert ledger_payload["worker"]["memory_hit_count"] >= 0


def test_read_only_worker_success_completes_with_artifacts(tmp_path, monkeypatch):
    class FakeWorker:
        name = "fake_worker"

        def run(self, prompt, worktree, route, task, dry_run=False):
            return WorkerResult(
                status="success",
                summary="Travel_with_me uses TypeScript and a Hono-style backend.",
                changed_files=[],
            )

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
    monkeypatch.setitem(__import__("orchestrator.scheduler", fromlist=["WORKERS"]).WORKERS, "claude_code", FakeWorker())

    service = OrchestratorService()
    result = service.submit_task(
        "generic",
        "只读调查项目用了什么语言，不修改文件，输出结论和修复计划。",
        "low",
        True,
        False,
        dry_run=False,
    )
    run_dir = Path(result["run_dir"])

    assert service.get_task_status(result["task_id"])["status"] == "COMPLETED_WITH_ARTIFACTS"
    review_payload = json.loads((run_dir / "review" / "review.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")
    assert review_payload["review_mode"] == "skipped_read_only"
    assert review_payload["approved"] is True
    assert "Travel_with_me uses TypeScript" in final_md
    task_payload = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
    assert task_payload["status"] == "COMPLETED_WITH_ARTIFACTS"
    assert task_payload["route_worker"] == "claude_code"


def test_repair_task_artifacts_backfills_opencode_summary_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    run_dir = service.artifacts.run_dir("t_opencode_repair")
    worker_dir = run_dir / "worker"
    worker_dir.mkdir(parents=True)
    stdout_path = worker_dir / "worker.stdout.jsonl"
    stdout_path.write_text(
        "\n".join([
            json.dumps({"type": "text", "part": {"text": "GLM 输出：桥梁与道路偏移 75m。"}}, ensure_ascii=False),
            json.dumps({
                "type": "step_finish",
                "timestamp": 1000,
                "part": {
                    "cost": 0.01,
                    "tokens": {
                        "input": 100,
                        "output": 20,
                        "cache": {"read": 80},
                    },
                },
            }),
        ]) + "\n",
        encoding="utf-8",
    )
    service.db.create_task({
        "task_id": "t_opencode_repair",
        "project_id": "travel_with_me",
        "repo_path": str(tmp_path),
        "user_goal": "只读复核，不修改文件。",
        "status": "COMPLETED_WITH_ARTIFACTS",
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:01:00Z",
        "route_worker": "opencode",
        "route_model": "opencode_go_glm52",
        "route_variant": "high",
        "pr_url": None,
        "run_dir": str(run_dir),
    })
    service.artifacts.write_json("t_opencode_repair", "task.json", {
        "task_id": "t_opencode_repair",
        "status": "QUEUED",
    })
    service.artifacts.write_json("t_opencode_repair", "result.json", {
        "status": "success",
        "summary": "OpenCode worker finished",
        "changed_files": [],
        "stdout_path": str(stdout_path),
    })
    service.artifacts.write_json("t_opencode_repair", "route.json", {
        "selected_worker": "opencode",
        "selected_model": "opencode_go_glm52",
    })
    service.artifacts.write_json("t_opencode_repair", "verify/verify.json", {
        "tests_passed": True,
        "build_passed": True,
    })
    service.artifacts.write_json("t_opencode_repair", "review/review.json", {
        "approved": True,
        "review_mode": "skipped_read_only",
        "can_create_pr": False,
    })

    result = service.repair_task_artifacts("t_opencode_repair")

    assert result["repaired_count"] == 1
    task_payload = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
    result_payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")
    metrics_payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert task_payload["status"] == "COMPLETED_WITH_ARTIFACTS"
    assert task_payload["route_worker"] == "opencode"
    assert result_payload["summary"] == "GLM 输出：桥梁与道路偏移 75m。"
    assert "桥梁与道路偏移" in final_md
    assert metrics_payload["total_cost_usd"] == 0.01
    assert metrics_payload["input_tokens"] == 100


def test_reaper_recovers_stale_read_only_success_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    service = OrchestratorService()
    run_dir = service.artifacts.run_dir("t_reap")
    control_dir = run_dir / "control"
    worker_dir = run_dir / "worker"
    control_dir.mkdir(parents=True)
    worker_dir.mkdir(parents=True)
    (control_dir / "process.json").write_text(
        json.dumps({
            "pid": 999999,
            "status": "running",
            "stdout_path": str(worker_dir / "worker.stream.jsonl"),
        }),
        encoding="utf-8",
    )
    (control_dir / "heartbeat.json").write_text(
        json.dumps({"status": "running", "last_seen": "2026-06-28T00:00:00Z"}),
        encoding="utf-8",
    )
    (worker_dir / "worker.stream.jsonl").write_text(
        json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "## Project Quality\n\nRead-only analysis completed.",
        }) + "\n",
        encoding="utf-8",
    )
    service.db.create_task({
        "task_id": "t_reap",
        "project_id": "travel_with_me",
        "repo_path": str(tmp_path),
        "user_goal": "只读评价项目质量，不修改文件，输出修复计划。",
        "status": "EXECUTING",
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:00:00Z",
        "route_worker": "claude_code",
        "route_model": "deepseek_pro",
        "route_variant": "",
        "pr_url": None,
        "run_dir": str(run_dir),
    })

    result = service.get_task_status("t_reap")

    assert result["status"] == "COMPLETED_WITH_ARTIFACTS"
    assert (run_dir / "final.md").exists()
    assert service.db.list_events("t_reap")[-1]["event_type"] == "stale_worker_reaped"


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
