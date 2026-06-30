from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from orchestrator.artifacts import ArtifactStore
from orchestrator.attempt_recording import AttemptMetricsRecorder
from orchestrator.db import TaskDB
from orchestrator.terminal_handlers import TerminalTaskHandler, degraded_mock_review
from orchestrator.verifier import VerifyResult
from orchestrator.workers.base import WorkerResult


def _task(task_id: str, run_dir: Path) -> dict:
    return {
        "task_id": task_id,
        "project_id": "generic",
        "repo_path": str(run_dir),
        "user_goal": "read-only project analysis",
        "risk_level": "medium",
        "run_dir": str(run_dir),
    }


def _route() -> dict:
    return {"selected_worker": "claude_code", "selected_model": "deepseek_pro"}


def _verify(run_dir: Path, *, changed_files: list[str] | None = None) -> VerifyResult:
    diff_path = run_dir / "verify" / "diff.patch"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("", encoding="utf-8")
    return VerifyResult(
        tests_passed=True,
        build_passed=True,
        command_results=[],
        changed_files=changed_files or [],
        diff_path=str(diff_path),
        forbidden_allowed=True,
        command_permissions_allowed=True,
        finished_at="2026-06-30T00:00:00Z",
    )


def _handler(tmp_path: Path, task_id: str) -> tuple[TerminalTaskHandler, Path, list[dict]]:
    artifacts = ArtifactStore(tmp_path / "runs")
    run_dir = artifacts.run_dir(task_id)
    db = TaskDB(tmp_path / "state.db")
    db.init()
    db.create_task(
        {
            "task_id": task_id,
            "project_id": "generic",
            "repo_path": str(tmp_path / "repo"),
            "user_goal": "read-only project analysis",
            "status": "EXECUTING",
            "created_at": "2026-06-30T00:00:00Z",
            "updated_at": "2026-06-30T00:00:00Z",
            "route_worker": "claude_code",
            "route_model": "deepseek_pro",
            "run_dir": str(run_dir),
        }
    )
    codex_usage_calls: list[dict] = []

    def dry_verify(task: dict) -> VerifyResult:
        return _verify(Path(task["run_dir"]))

    def record_usage(task_id: str, context: dict, review: dict) -> None:
        codex_usage_calls.append({"task_id": task_id, "context": context, "review": review})

    return (
        TerminalTaskHandler(
            artifacts=artifacts,
            metrics_recorder=AttemptMetricsRecorder(db),
            dry_verify_func=dry_verify,
            record_review_codex_usage=record_usage,
        ),
        run_dir,
        codex_usage_calls,
    )


def test_degraded_mock_review_is_not_publishable() -> None:
    review = degraded_mock_review(
        {"risk_level": "medium"},
        WorkerResult(
            status="success",
            summary="mock",
            degraded=True,
            mock_result=True,
            degradation_reason="dry-run worker unavailable",
        ),
        dry_run=True,
    )

    assert review["review_mode"] == "degraded_mock"
    assert review["approved"] is False
    assert review["can_create_pr"] is False
    assert review["mock_result"] is True


def test_handle_degraded_mock_writes_terminal_artifacts_and_metrics(tmp_path: Path) -> None:
    task_id = "t_degraded"
    handler, run_dir, usage_calls = _handler(tmp_path, task_id)
    worker = WorkerResult(
        status="success",
        summary="mock summary",
        changed_files=[],
        degraded=True,
        mock_result=True,
        degradation_reason="worker unavailable",
    )

    result = handler.handle_degraded_mock(
        task_id=task_id,
        task=_task(task_id, run_dir),
        route=_route(),
        worker_result=worker,
        last_attempt={"attempt_no": 1, "worker": "claude_code", "model": "deepseek_pro"},
        dry_run=True,
    )

    review = json.loads((run_dir / "review" / "review.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")

    assert result.status == "DRY_RUN_COMPLETED"
    assert result.event_type == "dry_run_completed"
    assert result.policy_success is False
    assert review["review_mode"] == "degraded_mock"
    assert review["approved"] is False
    assert metrics["failure_reason"] == "review_unavailable"
    assert metrics["review_approved"] is False
    assert usage_calls[0]["context"]["worker_degraded_mock"] is True
    assert "degraded_mock_result" in final_md


def test_handle_read_only_completion_writes_artifacts_and_policy_signal(tmp_path: Path) -> None:
    task_id = "t_read_only"
    handler, run_dir, usage_calls = _handler(tmp_path, task_id)
    verify = _verify(run_dir)
    worker = WorkerResult(
        status="success",
        summary="Project uses Python.",
        changed_files=[],
    )

    result = handler.handle_read_only_completion(
        task_id=task_id,
        task=_task(task_id, run_dir),
        route=_route(),
        worker_result=worker,
        verify_result=verify,
        forbidden=SimpleNamespace(allowed=True),
        last_attempt={"attempt_no": 1, "worker": "claude_code", "model": "deepseek_pro"},
        dry_run=False,
    )

    review = json.loads((run_dir / "review" / "review.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    final_md = (run_dir / "final.md").read_text(encoding="utf-8")

    assert result.status == "COMPLETED_WITH_ARTIFACTS"
    assert result.event_type == "read_only_completed"
    assert result.policy_success is True
    assert result.tests_passed is True
    assert result.codex_review_approved is True
    assert result.changed_paths == []
    assert review["review_mode"] == "skipped_read_only"
    assert review["approved"] is True
    assert metrics["failure_reason"] is None
    assert metrics["review_approved"] is True
    assert usage_calls[0]["context"]["read_only"] is True
    assert "Project uses Python." in final_md
