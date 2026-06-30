from __future__ import annotations

from orchestrator.failure_classifier import FailureClassification
from orchestrator.post_attempt_policy import decide_post_attempt
from orchestrator.workers.base import WorkerResult


def test_post_attempt_policy_marks_required_diff_success_without_changes_as_retryable_failure():
    result = WorkerResult(status="success", summary="done", changed_files=[])
    decision = decide_post_attempt(
        task={"user_goal": "fix login bug", "task_type": "simple_bugfix"},
        worker_result=result,
        failure=None,
        attempt={"worker": "claude_code", "model": "deepseek_pro"},
        attempt_index=0,
        retry_chain=[
            {"worker": "claude_code", "model": "deepseek_pro"},
            {"worker": "opencode", "model": "opencode_go_glm52"},
        ],
        dry_run=False,
        worker_name="ClaudeCodeWorker",
    )

    assert decision.kind == "no_diff"
    assert decision.status == "RETRYING"
    assert decision.event_type == "worker_no_diff"
    assert decision.failure.failure_reason == "worker_no_diff"
    assert result.status == "failed"
    assert "worker_no_diff" in result.risks


def test_post_attempt_policy_allows_read_only_success_without_changes():
    result = WorkerResult(status="success", summary="done", changed_files=[])
    decision = decide_post_attempt(
        task={"user_goal": "inspect project", "task_mode": "read_only", "expected_diff": False},
        worker_result=result,
        failure=None,
        attempt={"worker": "claude_code", "model": "deepseek_pro"},
        attempt_index=0,
        retry_chain=[{"worker": "claude_code", "model": "deepseek_pro"}],
        dry_run=False,
        worker_name="ClaudeCodeWorker",
    )

    assert decision.kind == "success"
    assert result.status == "success"


def test_post_attempt_policy_recovers_failed_worker_diff_for_verification():
    failure = FailureClassification("worker_failed", True, "retry", [])
    result = WorkerResult(status="failed", summary="patch produced", changed_files=["src/app.py"])
    decision = decide_post_attempt(
        task={"user_goal": "fix bug"},
        worker_result=result,
        failure=failure,
        attempt={"worker": "claude_code", "model": "deepseek_pro"},
        attempt_index=0,
        retry_chain=[{"worker": "claude_code", "model": "deepseek_pro"}],
        dry_run=False,
        worker_name="ClaudeCodeWorker",
    )

    assert decision.kind == "recover_failed_diff"
    assert decision.status == "EXECUTING"
    assert decision.event_type == "worker_failed_with_diff"
    assert "scheduler_recover_failed_worker_diff" in result.risks


def test_post_attempt_policy_builds_retry_payload_for_retryable_failure():
    failure = FailureClassification("worker_failed", True, "retry", ["boom"])
    result = WorkerResult(status="failed", summary="boom", changed_files=[])
    decision = decide_post_attempt(
        task={"user_goal": "fix bug"},
        worker_result=result,
        failure=failure,
        attempt={"worker": "claude_code", "model": "deepseek_pro"},
        attempt_index=0,
        retry_chain=[
            {"worker": "claude_code", "model": "deepseek_pro"},
            {"worker": "opencode", "model": "opencode_go_glm52"},
        ],
        dry_run=False,
        worker_name="ClaudeCodeWorker",
    )

    assert decision.kind == "retry"
    assert decision.status == "RETRYING"
    assert decision.payload["failed_worker"] == "claude_code"
    assert decision.payload["next_worker"] == "opencode"
