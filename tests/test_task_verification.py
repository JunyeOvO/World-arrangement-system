from __future__ import annotations

import json

from orchestrator.artifacts import ArtifactStore
from orchestrator.task_verification import TaskVerificationRunner
from orchestrator.verifier import VerifyResult
from orchestrator.workers.base import WorkerResult


def test_task_verification_runner_skips_project_commands_for_read_only_task(tmp_path):
    seen = {}

    def fake_verify(worktree, test_commands, build_commands, out_dir, permission_worker=None):
        seen["test_commands"] = test_commands
        seen["build_commands"] = build_commands
        seen["permission_worker"] = permission_worker
        return VerifyResult(True, True, changed_files=[], diff_path=str(out_dir / "diff.patch"))

    runner = TaskVerificationRunner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        verify_func=fake_verify,
        dry_verify_func=lambda task: VerifyResult(True, True),
    )
    run_dir = tmp_path / "runs" / "t_verify"
    task = {
        "task_id": "t_verify",
        "run_dir": str(run_dir),
        "user_goal": "只读分析项目质量，不修改文件。",
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "test_commands": ["npm test"],
        "build_commands": ["npm run build"],
        "forbidden_paths": [],
    }

    outcome = runner.run(
        task_id="t_verify",
        task=task,
        worktree_path=tmp_path,
        worker_result=WorkerResult(status="success", summary="done", changed_files=[]),
        last_attempt={"worker": "claude_code"},
        dry_run=False,
    )

    assert outcome.passed
    assert seen["test_commands"] == []
    assert seen["build_commands"] == []
    assert seen["permission_worker"] == "claude_code"
    assert json.loads((run_dir / "verify" / "verify.json").read_text(encoding="utf-8"))["tests_passed"] is True
    assert json.loads((run_dir / "verify" / "changed_files.json").read_text(encoding="utf-8")) == []


def test_task_verification_runner_classifies_forbidden_changed_files(tmp_path):
    def fake_verify(worktree, test_commands, build_commands, out_dir, permission_worker=None):
        return VerifyResult(True, True, changed_files=[".env"], diff_path=str(out_dir / "diff.patch"))

    runner = TaskVerificationRunner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        verify_func=fake_verify,
        dry_verify_func=lambda task: VerifyResult(True, True),
    )
    task = {
        "task_id": "t_forbidden",
        "run_dir": str(tmp_path / "runs" / "t_forbidden"),
        "user_goal": "fix config",
        "verification_policy": "changed_files_only",
        "forbidden_paths": [".env"],
    }

    outcome = runner.run(
        task_id="t_forbidden",
        task=task,
        worktree_path=tmp_path,
        worker_result=WorkerResult(status="success", summary="done", changed_files=[".env"]),
        last_attempt=None,
        dry_run=False,
    )

    assert not outcome.passed
    assert outcome.verify_result.forbidden_allowed is False
    assert outcome.failure.failure_reason == "forbidden_path"
