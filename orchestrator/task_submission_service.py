from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .codex_usage_recording import CodexUsageRecorder
from .db import TaskDB
from .project_registry import load_projects
from .task_submission import TaskSubmissionBuilder


class TaskSubmissionService:
    """Creates persisted task submissions and optionally starts execution."""

    def __init__(
        self,
        *,
        db: TaskDB,
        artifacts: ArtifactStore,
        submission_builder: TaskSubmissionBuilder,
        codex_usage: CodexUsageRecorder,
        load_projects_func: Callable[[], dict[str, dict[str, Any]]] = load_projects,
        new_task_id: Callable[[], str],
        now: Callable[[], str],
        execute_task: Callable[[dict[str, Any], dict[str, Any], bool], None],
        get_task_status: Callable[[str], dict[str, Any]],
    ) -> None:
        self.db = db
        self.artifacts = artifacts
        self.submission_builder = submission_builder
        self.codex_usage = codex_usage
        self.load_projects = load_projects_func
        self.new_task_id = new_task_id
        self.now = now
        self.execute_task = execute_task
        self.get_task_status = get_task_status

    def submit_task(
        self,
        project_id: str,
        user_goal: str,
        risk_level: str = "medium",
        auto_execute: bool = True,
        auto_pr: bool = False,
        dry_run: bool = False,
        force_worker: str | None = None,
        force_model: str | None = None,
        force_variant: str | None = None,
        image_paths: list[str] | None = None,
        image_base64: list[str] | None = None,
        task_mode: str | None = None,
        expected_diff: bool | None = None,
        verification_policy: str | None = None,
        read_budget_profile: str | None = None,
        read_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        projects = self.load_projects()
        if project_id not in projects:
            return {"status": "NEEDS_USER", "message": f"unknown project_id: {project_id}"}
        project = projects[project_id]
        task_id = self.new_task_id()
        run_dir = self.artifacts.run_dir(task_id)
        now = self.now()
        submission = self.submission_builder.build(
            task_id=task_id,
            run_dir=run_dir,
            now=now,
            project_id=project_id,
            project=project,
            user_goal=user_goal,
            risk_level=risk_level,
            auto_execute=auto_execute,
            auto_pr=auto_pr,
            force_worker=force_worker,
            force_model=force_model,
            force_variant=force_variant,
            image_paths=image_paths,
            image_base64=image_base64,
            task_mode=task_mode,
            expected_diff=expected_diff,
            verification_policy=verification_policy,
            read_budget_profile=read_budget_profile,
            read_budget=read_budget,
        )
        task = submission.task
        self.db.create_task(
            {
                "task_id": task_id,
                "project_id": project_id,
                "repo_path": project["repo"],
                "user_goal": user_goal,
                "status": "QUEUED",
                "created_at": now,
                "updated_at": now,
                "run_dir": str(run_dir),
            }
        )
        self.db.append_event(task_id, "created", None, "QUEUED", {"dry_run": dry_run})
        self.artifacts.write_json(task_id, "task.json", task)
        self.codex_usage.record_planning_dispatch(
            task_id=task_id,
            project_id=project_id,
            repo_path=project["repo"],
            user_goal=user_goal,
            risk_level=risk_level,
            auto_execute=auto_execute,
            auto_pr=task["auto_pr"],
            dry_run=dry_run,
            force_worker=force_worker,
            force_model=force_model,
            force_variant=force_variant,
            has_images=bool(image_paths or image_base64),
            protocol=submission.protocol,
            project_memory=submission.project_memory,
            run_dir=str(run_dir),
        )
        if auto_execute:
            self.execute_task(task, project, dry_run)
        return {"task_id": task_id, "status": self.get_task_status(task_id)["status"], "run_dir": str(Path(run_dir))}
