from pathlib import Path
from types import SimpleNamespace

from orchestrator.artifacts import ArtifactStore
from orchestrator.failure_classifier import FailureClassification
from orchestrator.task_completion_pipeline import TaskCompletionPipeline
from orchestrator.verifier import VerifyResult
from orchestrator.workers.base import WorkerResult


class FakeTerminalHandler:
    def __init__(self):
        self.read_only_called = False
        self.degraded_called = False

    def handle_degraded_mock(self, **kwargs):
        self.degraded_called = True
        return SimpleNamespace(
            status="NEEDS_USER",
            event_type="worker_degraded_mock_needs_user",
            payload={"worker": kwargs["worker_result"].__dict__},
            policy_success=False,
        )

    def handle_read_only_completion(self, **kwargs):
        self.read_only_called = True
        return SimpleNamespace(
            status="COMPLETED_WITH_ARTIFACTS",
            event_type="read_only_completed",
            payload={"worker": kwargs["worker_result"].__dict__},
            policy_success=True,
            tests_passed=True,
            codex_review_approved=True,
            changed_paths=[],
        )


class FakeVerificationRunner:
    def __init__(self, passed=True):
        self.passed = passed

    def run(self, **kwargs):
        verify_result = VerifyResult(
            tests_passed=self.passed,
            build_passed=True,
            changed_files=[] if self.passed else ["src/app.py"],
            diff_path=str(Path(kwargs["task"]["run_dir"]) / "verify" / "diff.patch"),
        )
        failure = None if self.passed else FailureClassification("tests_failed", True, "fix_tests", ["unit failed"])
        return SimpleNamespace(
            verify_result=verify_result,
            forbidden=SimpleNamespace(allowed=True, blocking_issues=[]),
            failure=failure,
            passed=self.passed,
        )


class FakeReviewRunner:
    def __init__(self, approved=True):
        self.approved = approved

    def run(self, **kwargs):
        review = {"approved": self.approved, "review_mode": "fake", "degraded": False}
        failure = None if self.approved else FailureClassification("review_failed", False, "fix_review", ["bad"])
        return SimpleNamespace(
            review=review,
            failure=failure,
            passed=self.approved,
            degraded_blocks_publish=False,
        )


class FakePublishRunner:
    def __init__(self, pr_created=False):
        self.pr_created = pr_created
        self.called = False

    def run(self, **kwargs):
        self.called = True
        return SimpleNamespace(
            status="PR_CREATED" if self.pr_created else "COMPLETED_WITH_PATCH",
            event_type="pr_created" if self.pr_created else "completed_with_patch",
            payload={"published": True},
            pr_created=self.pr_created,
        )


def _pipeline(tmp_path: Path, *, verification=None, review=None, publish=None):
    statuses = []
    policies = []
    metrics = []
    pipeline = TaskCompletionPipeline(
        artifacts=ArtifactStore(tmp_path / "runs"),
        terminal_handler=FakeTerminalHandler(),
        verification_runner=verification or FakeVerificationRunner(),
        review_runner=review or FakeReviewRunner(),
        publish_runner=publish or FakePublishRunner(),
        set_status=lambda task_id, status, event, payload: statuses.append((status, event, payload)),
        record_policy_learning=lambda *args, **kwargs: policies.append((args, kwargs)),
        write_attempt_metrics=lambda *args, **kwargs: metrics.append((args, kwargs)),
    )
    return pipeline, statuses, policies, metrics


def _task(tmp_path: Path, mode="patch") -> dict:
    run_dir = tmp_path / "runs" / "t_tail"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "task_id": "t_tail",
        "project_id": "proj",
        "run_dir": str(run_dir),
        "user_goal": "inspect project" if mode == "read_only" else "fix bug",
        "risk_level": "low",
        "task_mode": mode,
        "expected_diff": mode != "read_only",
    }


def _route() -> dict:
    return {"selected_worker": "claude_code", "selected_model": "deepseek_pro"}


def test_completion_pipeline_finishes_read_only_via_terminal_handler(tmp_path: Path):
    pipeline, statuses, policies, _ = _pipeline(tmp_path)

    result = pipeline.run(
        task_id="t_tail",
        task=_task(tmp_path, mode="read_only"),
        project={"repo": str(tmp_path)},
        route=_route(),
        worker_result=WorkerResult(status="success", summary="read-only result"),
        last_attempt={"attempt_no": 1, "worker": "claude_code", "model": "deepseek_pro"},
        worktree_path=tmp_path,
        branch="main",
    )

    assert result.status == "COMPLETED_WITH_ARTIFACTS"
    assert statuses[0][0:2] == ("VERIFYING", "verify_started")
    assert statuses[-1][0:2] == ("COMPLETED_WITH_ARTIFACTS", "read_only_completed")
    assert policies[-1][1]["success"] is True


def test_completion_pipeline_stops_on_verify_failure(tmp_path: Path):
    pipeline, statuses, policies, metrics = _pipeline(tmp_path, verification=FakeVerificationRunner(passed=False))

    result = pipeline.run(
        task_id="t_tail",
        task=_task(tmp_path),
        project={"repo": str(tmp_path)},
        route=_route(),
        worker_result=WorkerResult(status="success", summary="patch", changed_files=["src/app.py"]),
        last_attempt={"attempt_no": 2, "worker": "claude_code", "model": "deepseek_pro"},
        worktree_path=tmp_path,
        branch="main",
    )

    assert result.status == "FAILED_FINAL"
    assert statuses[-1][0:2] == ("FAILED_FINAL", "verify_failed")
    assert policies[-1][1]["success"] is False
    assert metrics


def test_completion_pipeline_reviews_and_publishes_patch(tmp_path: Path):
    publisher = FakePublishRunner(pr_created=True)
    pipeline, statuses, policies, metrics = _pipeline(tmp_path, publish=publisher)

    result = pipeline.run(
        task_id="t_tail",
        task=_task(tmp_path),
        project={"repo": str(tmp_path), "allow_remote_push": True},
        route=_route(),
        worker_result=WorkerResult(status="success", summary="patch", changed_files=["src/app.py"]),
        last_attempt={"attempt_no": 1, "worker": "claude_code", "model": "deepseek_pro"},
        worktree_path=tmp_path,
        branch="ai/t_tail",
    )

    assert result.status == "PR_CREATED"
    assert publisher.called is True
    assert ("POLICY_LEARNING", "policy_learning", {}) in statuses
    assert statuses[-1][0:2] == ("PR_CREATED", "pr_created")
    assert policies[-1][1]["pr_created"] is True
    assert metrics
