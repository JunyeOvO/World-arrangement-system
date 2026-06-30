from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .failure_classifier import FailureClassification, classify_verify_failure
from .read_only_completion import skip_project_verification_for_read_only_task
from .risk_policy import check_changed_files
from .task_protocol import verification_commands_for_policy
from .verifier import VerifyResult, verify, write_verify_result


@dataclass
class TaskVerificationOutcome:
    verify_result: VerifyResult
    forbidden: Any
    failure: FailureClassification | None = None

    @property
    def passed(self) -> bool:
        return self.failure is None


class TaskVerificationRunner:
    """Runs project verification and classifies verification failure."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        verify_func: Callable[..., VerifyResult] = verify,
        dry_verify_func: Callable[[dict[str, Any]], VerifyResult],
    ) -> None:
        self.artifacts = artifacts
        self.verify_func = verify_func
        self.dry_verify_func = dry_verify_func

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        worktree_path: Path,
        worker_result: Any,
        last_attempt: dict[str, Any] | None,
        dry_run: bool,
    ) -> TaskVerificationOutcome:
        test_commands, build_commands = verification_commands_for_policy(
            str(task.get("verification_policy") or "full"),
            list(task.get("test_commands", [])),
            list(task.get("build_commands", [])),
        )
        if skip_project_verification_for_read_only_task(task, worker_result):
            test_commands = []
            build_commands = []

        verify_result = (
            self.dry_verify_func(task)
            if dry_run
            else self.verify_func(
                worktree_path,
                test_commands,
                build_commands,
                Path(task["run_dir"]) / "verify",
                permission_worker=last_attempt["worker"] if last_attempt else None,
            )
        )
        forbidden = check_changed_files(verify_result.changed_files, task.get("forbidden_paths"))
        verify_result.forbidden_allowed = forbidden.allowed
        write_verify_result(verify_result, Path(task["run_dir"]) / "verify" / "verify.json")
        self.artifacts.write_json(task_id, "verify/changed_files.json", verify_result.changed_files)

        failure = None
        if (
            not verify_result.tests_passed
            or not verify_result.build_passed
            or not forbidden.allowed
            or not verify_result.command_permissions_allowed
        ):
            failure = classify_verify_failure(
                tests_passed=verify_result.tests_passed,
                build_passed=verify_result.build_passed,
                forbidden_allowed=forbidden.allowed,
                command_permissions_allowed=verify_result.command_permissions_allowed,
                evidence=[
                    *forbidden.blocking_issues,
                    *[
                        result.permission_reason
                        for result in verify_result.command_results
                        if not result.permission_allowed or result.permission_requires_ask
                    ],
                ],
            )
        return TaskVerificationOutcome(verify_result=verify_result, forbidden=forbidden, failure=failure)
