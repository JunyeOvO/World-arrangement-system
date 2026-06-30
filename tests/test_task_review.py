from __future__ import annotations

import json

from orchestrator.task_review import TaskReviewRunner, review_degraded_blocks_publish
from orchestrator.verifier import VerifyResult


class Forbidden:
    allowed = True


def test_task_review_runner_records_approved_review(tmp_path):
    recorded = []

    def fake_review(inputs, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"approved": True, "can_create_pr": True, "review_mode": "codex"}
        output.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    runner = TaskReviewRunner(
        review_func=fake_review,
        record_codex_usage=lambda task_id, inputs, review: recorded.append((task_id, inputs, review)),
    )

    outcome = runner.run(
        task_id="t_review",
        task={"task_id": "t_review", "run_dir": str(tmp_path), "risk_level": "low"},
        verify_result=VerifyResult(True, True, changed_files=["src/app.py"]),
        forbidden=Forbidden(),
        dry_run=False,
    )

    assert outcome.passed
    assert outcome.failure is None
    assert outcome.review_inputs["changed_files"] == ["src/app.py"]
    assert recorded[0][0] == "t_review"


def test_task_review_runner_blocks_degraded_review_for_medium_risk(tmp_path):
    runner = TaskReviewRunner(
        review_func=lambda inputs, output: {
            "approved": True,
            "degraded": True,
            "available": False,
            "error": "review unavailable",
        },
        record_codex_usage=lambda task_id, inputs, review: None,
    )

    outcome = runner.run(
        task_id="t_degraded",
        task={"task_id": "t_degraded", "run_dir": str(tmp_path), "risk_level": "medium"},
        verify_result=VerifyResult(True, True, changed_files=[]),
        forbidden=Forbidden(),
        dry_run=True,
    )

    assert review_degraded_blocks_publish({"risk_level": "medium"}, outcome.review)
    assert outcome.degraded_blocks_publish
    assert outcome.failure.failure_reason == "review_unavailable"


def test_task_review_runner_classifies_rejected_review(tmp_path):
    runner = TaskReviewRunner(
        review_func=lambda inputs, output: {"approved": False, "blocking_issues": ["needs changes"]},
        record_codex_usage=lambda task_id, inputs, review: None,
    )

    outcome = runner.run(
        task_id="t_rejected",
        task={"task_id": "t_rejected", "run_dir": str(tmp_path), "risk_level": "low"},
        verify_result=VerifyResult(True, True, changed_files=[]),
        forbidden=Forbidden(),
        dry_run=False,
    )

    assert not outcome.passed
    assert not outcome.degraded_blocks_publish
    assert outcome.failure.failure_reason == "review_rejected"
