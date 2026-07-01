from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .pr import create_pr_or_patch
from .reviewer import run_codex_review
from .read_only_completion import (
    task_requires_diff as _task_requires_diff,
)
from .service_composition import build_orchestrator_components
from .verifier import verify
from .worker_prompt import build_worker_prompt
from .workers.claude_code_worker import ClaudeCodeWorker
from .workers.opencode_worker import OpenCodeWorker
from .state_machine import can_transition


WORKERS = {
    "claude_code": ClaudeCodeWorker(),
    "opencode": OpenCodeWorker(),
}


def new_task_id() -> str:
    return "t_" + time.strftime("%Y%m%d_%H%M%S", time.localtime()) + "_" + uuid.uuid4().hex[:6]


class OrchestratorService:
    def __init__(self) -> None:
        self.components = build_orchestrator_components(
            profile_project=self.profile_project,
            detect_project=self.detect_project,
            world_create_plan=self.world_create_plan,
            submit_task=self.submit_task,
            execute_task=self._execute,
            get_task_status=self.get_task_status,
            new_task_id=new_task_id,
            now=_now,
            dry_verify_func=_dry_verify,
            task_requires_diff=_task_requires_diff,
            verify_func=verify,
            review_func=run_codex_review,
            publish_func=create_pr_or_patch,
            build_prompt=_worker_prompt,
            workers=WORKERS,
            default_worker=ClaudeCodeWorker(),
        )
        for name, value in self.components.__dict__.items():
            setattr(self, name, value)

    def list_projects(self, query: str | None = None) -> dict[str, Any]:
        return self.project_lookup.list_projects(query)

    def detect_project(self, repo_path: str | None = None, git_remote_url: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        return self.project_lookup.detect_project(repo_path=repo_path, git_remote_url=git_remote_url, cwd=cwd)

    # ── World vNext lightweight tools ──

    def world_bootstrap(
        self,
        repo_path: str,
        user_prompt: str = "本项目开发使用 World 系统",
        preferred_write_policy: str = "zero_write",
    ) -> dict[str, Any]:
        return self.world_runtime.bootstrap(repo_path, user_prompt, preferred_write_policy)

    def world_profile_project(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        """World-named wrapper around the adaptive project profiler."""
        return self.world_runtime.profile(repo_path, force)

    def world_create_plan(
        self,
        repo_path: str,
        user_goal: str,
        risk_level: str = "medium",
        preferred_write_policy: str = "zero_write",
    ) -> dict[str, Any]:
        return self.world_runtime.create_plan(repo_path, user_goal, risk_level, preferred_write_policy)

    def world_doctor(self, repo_path: str | None = None) -> dict[str, Any]:
        return self.world_runtime.doctor(repo_path)

    def submit_current_project_task(
        self,
        user_goal: str,
        repo_path: str | None = None,
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
        return self.current_project_tasks.submit_current_project_task(
            user_goal,
            repo_path=repo_path,
            risk_level=risk_level,
            auto_execute=auto_execute,
            auto_pr=auto_pr,
            dry_run=dry_run,
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
        return self.task_submission.submit_task(
            project_id,
            user_goal,
            risk_level,
            auto_execute,
            auto_pr,
            dry_run,
            force_worker,
            force_model,
            force_variant,
            image_paths,
            image_base64,
            task_mode,
            expected_diff,
            verification_policy,
            read_budget_profile,
            read_budget,
        )

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self.task_operations.get_task_status(task_id)

    def read_task_result(self, task_id: str, sections: list[str] | None = None) -> dict[str, Any]:
        return self.task_operations.read_task_result(task_id, sections)

    def record_task_baseline(
        self,
        task_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        actual: bool = False,
        baseline_kind: str | None = None,
    ) -> dict[str, Any]:
        return self.task_operations.record_task_baseline(
            task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual=actual,
            baseline_kind=baseline_kind,
        )

    def repair_task_artifacts(self, task_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return self.task_operations.repair_task_artifacts(task_id, limit)

    def open_task_artifacts(self, task_id: str) -> dict[str, Any]:
        return self.task_operations.open_task_artifacts(task_id)

    def get_task_control(self, task_id: str) -> dict[str, Any]:
        return self.task_operations.get_task_control(task_id)

    def cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        return self.task_operations.cancel_task(task_id, reason)

    def rollback_task(self, task_id: str, cleanup_worktree: bool = True) -> dict[str, Any]:
        return self.task_operations.rollback_task(task_id, cleanup_worktree)

    # ── Dynamic Approval Graph methods ──

    def get_approval_decision(self, project_id: str, user_goal: str, risk_level: str = "medium") -> dict[str, Any]:
        """Get the approval decision for a potential task without submitting it."""
        return self.approval_policy.decision_for_goal(project_id, user_goal, risk_level)

    def approve_task(self, task_id: str, user: str = "codex") -> dict[str, Any]:
        """User approves a task awaiting approval."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if not can_transition(str(task.get("status") or ""), "PLANNED"):
            return {
                "status": "INVALID_STATE",
                "task_id": task_id,
                "from_state": task.get("status"),
                "to_state": "PLANNED",
                "reason": "approval is not allowed from current state",
            }
        result = self.approval_policy.approve_task(task, user=user)
        self.execution_callbacks.set_status(
            task_id,
            "PLANNED",
            "approval_approved",
            {"user": user, "decision": "approved"},
        )
        resumed_task = self.db.get_task(task_id) or task
        resumed_task["_approval_granted"] = True
        self._execute(resumed_task, self._project_for_task(resumed_task), dry_run=False)
        current = self.db.get_task(task_id)
        return {**result, "resumed": True, "status_after_approval": current.get("status") if current else None}

    def reject_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        """User rejects a task awaiting approval."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if not can_transition(str(task.get("status") or ""), "CANCELLED"):
            return {
                "status": "INVALID_STATE",
                "task_id": task_id,
                "from_state": task.get("status"),
                "to_state": "CANCELLED",
                "reason": "rejection is not allowed from current state",
            }
        result = self.approval_policy.reject_task(task, reason)
        cancel_result = self.cancel_task(task_id, reason=f"User rejected: {reason}")
        if cancel_result.get("status") == "INVALID_STATE":
            return cancel_result
        return {**result, "cancelled": cancel_result.get("status") == "CANCELLED"}

    def _project_for_task(self, task: dict[str, Any]) -> dict[str, Any]:
        repo_path = str(task.get("repo_path") or "")
        if repo_path:
            detected = self.detect_project(repo_path=repo_path)
            project = detected.get("project") if isinstance(detected, dict) else None
            if isinstance(project, dict) and project.get("project_id") == task.get("project_id"):
                return project
        return {
            "project_id": task.get("project_id", ""),
            "name": task.get("project_id", ""),
            "repo": repo_path,
            "stack": [],
            "test_commands": [],
            "build_commands": [],
            "forbidden_paths": [],
            "default_worker": task.get("route_worker") or "claude_code",
            "default_model": task.get("route_model") or "deepseek_pro",
            "allow_auto_pr": False,
            "allow_remote_push": False,
        }

    def list_learned_rules(self, project_id: str) -> dict[str, Any]:
        """List learned approval rules for a project."""
        return self.approval_policy.list_learned_rules(project_id)

    def revoke_learned_rule(self, pattern_id: int) -> dict[str, Any]:
        """Revoke (deactivate) a learned approval rule."""
        return self.approval_policy.revoke_learned_rule(pattern_id)

    def explain_approval(self, task_id: str) -> dict[str, Any]:
        """Explain the approval decision for an existing task."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        return self.approval_policy.explain_task_approval(task)

    def list_policy_suggestions(self, project_id: str) -> dict[str, Any]:
        """List pending policy suggestions for a project."""
        return self.approval_policy.list_policy_suggestions(project_id)

    def approve_policy_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """Approve a policy suggestion and create a matching override."""
        return self.approval_policy.approve_policy_suggestion(suggestion_id, user="codex")

    def reject_policy_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """Reject a policy suggestion."""
        return self.approval_policy.reject_policy_suggestion(suggestion_id)

    # ── Adaptive Project Layer methods ──

    def scan_project_roots(self, roots: list[str] | None = None, max_depth: int = 3) -> dict[str, Any]:
        """Scan root directories for project candidates (.git repos)."""
        return self.project_commands.scan_project_roots(roots, max_depth)

    def discover_projects(self, roots: list[str] | None = None, max_depth: int = 3) -> dict[str, Any]:
        """Scan + profile: discover projects and return full profiles."""
        return self.project_commands.discover_projects(roots, max_depth)

    def profile_project(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        """Deep-profile a single project."""
        return self.project_commands.profile_project(repo_path, force)

    def register_project(self, repo_path: str, confirm: bool = False) -> dict[str, Any]:
        """Register a discovered project into projects.yaml."""
        return self.project_commands.register_project(repo_path, confirm)

    def refresh_project_profile(self, project_id: str) -> dict[str, Any]:
        """Refresh a registered project's profile."""
        return self.project_commands.refresh_project_profile(project_id)

    def list_unregistered_projects(self) -> dict[str, Any]:
        """List projects in pending_confirmation status."""
        return self.project_commands.list_unregistered_projects()

    def confirm_project_profile(self, project_id: str) -> dict[str, Any]:
        """Confirm a pending project."""
        return self.project_commands.confirm_project_profile(project_id)

    def ignore_project(self, repo_path: str, reason: str = "") -> dict[str, Any]:
        """Add a project path to the ignore list."""
        return self.project_commands.ignore_project(repo_path, reason)

    def _execute(self, task: dict[str, Any], project: dict[str, Any], dry_run: bool = False) -> None:
        self.task_execution.execute(task, project, dry_run=dry_run)

    def reap_stale_worker_task(self, task: dict[str, Any]) -> None:
        self.execution_callbacks.reap_stale_worker_task(task)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _worker_prompt(task: dict[str, Any], route: dict[str, Any]) -> str:
    return build_worker_prompt(task, route, task_requires_diff=_task_requires_diff)


def _dry_verify(task: dict[str, Any]):
    from .verifier import VerifyResult

    diff_path = str(Path(task["run_dir"]) / "verify" / "diff.patch")
    Path(diff_path).parent.mkdir(parents=True, exist_ok=True)
    Path(diff_path).write_text("", encoding="utf-8")
    return VerifyResult(
        tests_passed=True,
        build_passed=True,
        command_results=[],
        changed_files=[],
        diff_path=diff_path,
        forbidden_allowed=True,
        command_permissions_allowed=True,
        finished_at=_now(),
    )
