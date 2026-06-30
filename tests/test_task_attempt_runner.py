from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.failure_classifier import FailureClassification
from orchestrator.task_attempt_runner import TaskAttemptRunner
from orchestrator.worker_attempt_executor import WorkerAttemptOutcome
from orchestrator.workers.base import WorkerResult


class DummyWorker:
    name = "DummyWorker"


class FakeAttemptExecutor:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcomes.pop(0)


def _runner(tmp_path: Path, outcomes, statuses=None, metrics=None) -> TaskAttemptRunner:
    statuses = statuses if statuses is not None else []
    metrics = metrics if metrics is not None else []
    return TaskAttemptRunner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        attempt_executor=FakeAttemptExecutor(outcomes),
        workers={"claude_code": DummyWorker(), "opencode": DummyWorker()},
        default_worker=DummyWorker(),
        set_status=lambda task_id, status, event, payload: statuses.append((task_id, status, event, payload)),
        write_attempt_metrics=lambda *args, **kwargs: metrics.append((args, kwargs)),
    )


def _task(tmp_path: Path) -> dict:
    run_dir = tmp_path / "runs" / "t_attempts"
    run_dir.mkdir(parents=True)
    return {
        "task_id": "t_attempts",
        "run_dir": str(run_dir),
        "user_goal": "inspect project",
        "task_mode": "read_only",
        "expected_diff": False,
    }


def test_attempt_runner_returns_success_result(tmp_path: Path):
    worker_result = WorkerResult(status="success", summary="done")
    runner = _runner(
        tmp_path,
        [WorkerAttemptOutcome("completed", {"worker": "claude_code", "model": "deepseek_pro"}, worker_result=worker_result)],
    )

    result = runner.run(
        task_id="t_attempts",
        task=_task(tmp_path),
        route={"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        worktree_path=tmp_path,
    )

    assert result.completed is True
    assert result.final_result is worker_result
    assert result.last_attempt["worker"] == "claude_code"
    assert result.terminal_status is None


def test_attempt_runner_records_retry_transition_then_succeeds(tmp_path: Path):
    statuses = []
    first_failure = FailureClassification("worker_failed", True, "retry", ["boom"])
    failed = WorkerResult(status="failed", summary="boom", changed_files=[])
    succeeded = WorkerResult(status="success", summary="done", changed_files=["src/app.py"])
    runner = _runner(
        tmp_path,
        [
            WorkerAttemptOutcome("completed", {"worker": "claude_code", "model": "deepseek_pro"}, worker_result=failed, failure=first_failure),
            WorkerAttemptOutcome("completed", {"worker": "opencode", "model": "opencode_go_glm52"}, worker_result=succeeded),
        ],
        statuses=statuses,
    )

    result = runner.run(
        task_id="t_attempts",
        task={**_task(tmp_path), "task_mode": "patch", "expected_diff": True},
        route={
            "selected_worker": "claude_code",
            "selected_model": "deepseek_pro",
            "retry_chain": [
                {"worker": "claude_code", "model": "deepseek_pro"},
                {"worker": "opencode", "model": "opencode_go_glm52"},
            ],
        },
        worktree_path=tmp_path,
    )

    assert result.completed is True
    assert result.final_result is succeeded
    assert statuses[0][1:3] == ("RETRYING", "worker_retry")
    assert statuses[0][3]["next_worker"] == "opencode"


def test_attempt_runner_returns_preflight_denied_terminal_signal(tmp_path: Path):
    failure = FailureClassification("forbidden_path", False, "block", [".env"])
    runner = _runner(
        tmp_path,
        [
            WorkerAttemptOutcome(
                "preflight_denied",
                {"worker": "claude_code", "model": "deepseek_pro"},
                failure=failure,
                permission={"allowed": False},
            )
        ],
    )

    result = runner.run(
        task_id="t_attempts",
        task=_task(tmp_path),
        route={"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        worktree_path=tmp_path,
    )

    assert result.completed is False
    assert result.terminal_status == "BLOCKED"
    assert result.terminal_event == "permission_denied"
    assert result.policy_signal.incident is True
    assert result.policy_signal.worker == "claude_code"
