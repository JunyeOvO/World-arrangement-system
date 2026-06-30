from __future__ import annotations

from typing import Any, Callable

from .project_registry import ProjectMatch, detect_project


class CurrentProjectTaskService:
    """Submits a task for the project detected from the current repository."""

    def __init__(
        self,
        *,
        detect_project_func: Callable[..., ProjectMatch] = detect_project,
        submit_task: Callable[..., dict[str, Any]],
    ) -> None:
        self.detect_project = detect_project_func
        self.submit_task = submit_task

    def submit_current_project_task(
        self,
        user_goal: str,
        repo_path: str | None = None,
        risk_level: str = "medium",
        auto_execute: bool = True,
        auto_pr: bool = False,
        dry_run: bool = False,
        image_paths: list[str] | None = None,
        image_base64: list[str] | None = None,
        task_mode: str | None = None,
        expected_diff: bool | None = None,
        verification_policy: str | None = None,
        read_budget_profile: str | None = None,
        read_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        match = self.detect_project(repo_path=repo_path or ".")
        if match.needs_user or not match.project_id:
            return {"status": "NEEDS_USER", "message": "project could not be detected", "match": match.__dict__}
        return self.submit_task(
            match.project_id,
            user_goal,
            risk_level,
            auto_execute,
            auto_pr,
            dry_run,
            image_paths=image_paths,
            image_base64=image_base64,
            task_mode=task_mode,
            expected_diff=expected_diff,
            verification_policy=verification_policy,
            read_budget_profile=read_budget_profile,
            read_budget=read_budget,
        )
