from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure_classifier import FailureClassification, classify_review_failure
from .reviewer import run_codex_review


@dataclass
class TaskReviewOutcome:
    review_inputs: dict[str, Any]
    review: dict[str, Any]
    failure: FailureClassification | None = None

    @property
    def passed(self) -> bool:
        return self.failure is None and bool(self.review.get("approved"))

    @property
    def degraded_blocks_publish(self) -> bool:
        return self.failure is not None and bool(self.review.get("degraded"))


class TaskReviewRunner:
    """Runs the Codex review gate and classifies review outcomes."""

    def __init__(
        self,
        *,
        review_func: Callable[[dict[str, Any], Path], dict[str, Any]] = run_codex_review,
        record_codex_usage: Callable[[str, dict[str, Any], dict[str, Any]], None],
    ) -> None:
        self.review_func = review_func
        self.record_codex_usage = record_codex_usage

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        verify_result: Any,
        forbidden: Any,
        dry_run: bool,
    ) -> TaskReviewOutcome:
        review_inputs = {
            "task_id": task_id,
            "risk_level": task["risk_level"],
            "dry_run": dry_run,
            "tests_passed": verify_result.tests_passed,
            "forbidden_paths_touched": not forbidden.allowed,
            "changed_files": verify_result.changed_files,
        }
        review = self.review_func(review_inputs, Path(task["run_dir"]) / "review" / "review.json")
        self.record_codex_usage(task_id, review_inputs, review)
        failure = None
        if review_degraded_blocks_publish(task, review):
            failure = classify_review_failure({**review, "available": False})
        elif not review.get("approved"):
            failure = classify_review_failure(review)
        return TaskReviewOutcome(review_inputs=review_inputs, review=review, failure=failure)


def review_degraded_blocks_publish(task: dict[str, Any], review: dict[str, Any]) -> bool:
    if not review.get("degraded"):
        return False
    return str(task.get("risk_level", "medium")).lower() in {"medium", "high", "max"}
