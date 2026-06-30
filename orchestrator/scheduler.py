from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .codex_usage_recording import CodexUsageRecorder
from .config import ensure_runtime_dirs
from .db import TaskDB
from .pr import create_pr_or_patch
from .project_registry import detect_project, load_projects
from .task_protocol import (
    apply_read_budget_to_route,
)
from .task_artifact_repair import TaskArtifactRepairService
from .task_lifecycle import TaskLifecycleController
from .task_outcome_recording import TaskOutcomeRecorder
from .task_publish import TaskPublishRunner
from .task_route_planner import TaskRoutePlanner
from .project_commands import (
    handle_confirm_project_profile,
    handle_discover_projects,
    handle_ignore_project,
    handle_list_unregistered_projects,
    handle_profile_project,
    handle_refresh_project_profile,
    handle_register_project,
    handle_scan_project_roots,
)
from .reviewer import run_codex_review
from .read_only_completion import (
    task_requires_diff as _task_requires_diff,
    task_requests_project_verification as _task_requests_project_verification,
)
from .stale_worker_reaper import StaleWorkerReaper
from .task_completion_pipeline import TaskCompletionPipeline
from .task_execution_gate import TaskExecutionGate
from .task_attempt_runner import TaskAttemptRunner
from .task_preparation import TaskPreparationService
from .task_review import TaskReviewRunner
from .task_submission import TaskSubmissionBuilder
from .task_operations import TaskOperationsService
from .terminal_handlers import TerminalTaskHandler
from .task_verification import TaskVerificationRunner
from .verifier import verify
from .approval_policy_service import ApprovalPolicyService
from .attempt_recording import AttemptMetricsRecorder
from .policy_learning import PolicyLearningRecorder
from .worker_permission_audit import WorkerPermissionAuditor
from .worker_attempt_executor import WorkerAttemptExecutor
from .worker_prompt import build_worker_prompt
from .world_runtime_service import WorldRuntimeService
from .workers.claude_code_worker import ClaudeCodeWorker
from .workers.opencode_worker import OpenCodeWorker


WORKERS = {
    "claude_code": ClaudeCodeWorker(),
    "opencode": OpenCodeWorker(),
}


def new_task_id() -> str:
    return "t_" + time.strftime("%Y%m%d_%H%M%S", time.localtime()) + "_" + uuid.uuid4().hex[:6]


class OrchestratorService:
    def __init__(self) -> None:
        self.paths = ensure_runtime_dirs()
        self.db = TaskDB(self.paths.state_db)
        self.db.init()
        self.artifacts = ArtifactStore(self.paths.runs)
        self.attempt_metrics = AttemptMetricsRecorder(self.db)
        self.permission_auditor = WorkerPermissionAuditor(self.db)
        self.submission_builder = TaskSubmissionBuilder()
        self.artifact_repair = TaskArtifactRepairService(
            db=self.db,
            artifacts=self.artifacts,
            metrics_recorder=self.attempt_metrics,
        )
        self.outcome_recorder = TaskOutcomeRecorder(db=self.db, artifacts=self.artifacts)
        self.codex_usage = CodexUsageRecorder(
            db=self.db,
            artifacts=self.artifacts,
            write_token_ledger=self.attempt_metrics.write_token_ledger,
        )
        self.world_runtime = WorldRuntimeService(
            profile_project=self.profile_project,
            detect_project=self.detect_project,
            model_metrics_summary=self.db.model_metrics_summary,
            new_run_id=new_task_id,
        )
        self.route_planner = TaskRoutePlanner(
            artifacts=self.artifacts,
            model_metrics_summary=self.db.model_metrics_summary,
            world_plan_factory=self.world_create_plan,
        )
        self.preparation = TaskPreparationService(
            artifacts=self.artifacts,
            set_status=self._set_status,
        )
        self.lifecycle = TaskLifecycleController(
            self.db,
            now=_now,
            sync_task_artifact=self.artifact_repair.sync_task_artifact_from_db,
            record_task_outcome=self.outcome_recorder.record_task_outcome,
        )
        self.attempt_executor = WorkerAttemptExecutor(
            artifacts=self.artifacts,
            permission_auditor=self.permission_auditor,
            metrics_recorder=self.attempt_metrics,
            workers=WORKERS,
            default_worker=ClaudeCodeWorker(),
            now=_now,
            set_status=self._set_status,
            build_prompt=_worker_prompt,
        )
        self.attempt_runner = TaskAttemptRunner(
            artifacts=self.artifacts,
            attempt_executor=self.attempt_executor,
            workers=WORKERS,
            default_worker=ClaudeCodeWorker(),
            set_status=self._set_status,
            write_attempt_metrics=self._write_attempt_metrics,
        )
        self.verification_runner = TaskVerificationRunner(
            artifacts=self.artifacts,
            verify_func=verify,
            dry_verify_func=_dry_verify,
        )
        self.review_runner = TaskReviewRunner(
            review_func=run_codex_review,
            record_codex_usage=self.codex_usage.record_review_usage,
        )
        self.publish_runner = TaskPublishRunner(
            artifacts=self.artifacts,
            db=self.db,
            publish_func=create_pr_or_patch,
            now=_now,
        )
        self.terminal_handler = TerminalTaskHandler(
            artifacts=self.artifacts,
            metrics_recorder=self.attempt_metrics,
            dry_verify_func=_dry_verify,
            record_review_codex_usage=self.codex_usage.record_review_usage,
        )
        self.completion_pipeline = TaskCompletionPipeline(
            artifacts=self.artifacts,
            terminal_handler=self.terminal_handler,
            verification_runner=self.verification_runner,
            review_runner=self.review_runner,
            publish_runner=self.publish_runner,
            set_status=self._set_status,
            record_policy_learning=self._record_policy_learning,
            write_attempt_metrics=self._write_attempt_metrics,
        )
        self.stale_worker_reaper = StaleWorkerReaper(
            artifacts=self.artifacts,
            dry_verify_func=_dry_verify,
            task_requires_diff=_task_requires_diff,
        )
        self.policy_learning = PolicyLearningRecorder(self.db)
        self.approval_policy = ApprovalPolicyService(self.db)
        self.execution_gate = TaskExecutionGate(
            artifacts=self.artifacts,
            approval_policy=self.approval_policy,
        )
        self.task_operations = TaskOperationsService(
            db=self.db,
            artifacts=self.artifacts,
            artifact_repair=self.artifact_repair,
            reap_stale_worker_task=self._reap_stale_worker_task,
            record_policy_learning=self._record_policy_learning,
            write_token_ledger=self.attempt_metrics.write_token_ledger,
            now=_now,
        )

    def list_projects(self, query: str | None = None) -> dict[str, Any]:
        projects = load_projects()
        rows = list(projects.values())
        if query:
            q = query.lower()
            rows = [p for p in rows if q in p.get("project_id", "").lower() or q in p.get("name", "").lower()]
        return {"projects": rows}

    def detect_project(self, repo_path: str | None = None, git_remote_url: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        match = detect_project(repo_path=repo_path, git_remote_url=git_remote_url, cwd=cwd)
        health = _project_registration_health(match.project, repo_path or cwd)
        return {
            "project_id": match.project_id,
            "confidence": match.confidence,
            "matched_by": match.matched_by,
            "needs_user": match.needs_user,
            "project": match.project,
            "health": health,
        }

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
        image_paths: list[str] | None = None,
        image_base64: list[str] | None = None,
        task_mode: str | None = None,
        expected_diff: bool | None = None,
        verification_policy: str | None = None,
        read_budget_profile: str | None = None,
        read_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        match = detect_project(repo_path=repo_path or ".")
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
        projects = load_projects()
        if project_id not in projects:
            return {"status": "NEEDS_USER", "message": f"unknown project_id: {project_id}"}
        project = projects[project_id]
        task_id = new_task_id()
        run_dir = self.artifacts.run_dir(task_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
            self._execute(task, project, dry_run=dry_run)
        return {"task_id": task_id, "status": self.get_task_status(task_id)["status"], "run_dir": str(run_dir)}

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
        return self.approval_policy.approve_task(task, user=user)

    def reject_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        """User rejects a task awaiting approval."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        result = self.approval_policy.reject_task(task, reason)
        self.cancel_task(task_id, reason=f"User rejected: {reason}")
        return result

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
        return handle_scan_project_roots(roots, max_depth)

    def discover_projects(self, roots: list[str] | None = None, max_depth: int = 3) -> dict[str, Any]:
        """Scan + profile: discover projects and return full profiles."""
        return handle_discover_projects(roots, max_depth)

    def profile_project(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        """Deep-profile a single project."""
        return handle_profile_project(repo_path, force)

    def register_project(self, repo_path: str, confirm: bool = False) -> dict[str, Any]:
        """Register a discovered project into projects.yaml."""
        return handle_register_project(repo_path, confirm)

    def refresh_project_profile(self, project_id: str) -> dict[str, Any]:
        """Refresh a registered project's profile."""
        return handle_refresh_project_profile(project_id)

    def list_unregistered_projects(self) -> dict[str, Any]:
        """List projects in pending_confirmation status."""
        return handle_list_unregistered_projects()

    def confirm_project_profile(self, project_id: str) -> dict[str, Any]:
        """Confirm a pending project."""
        return handle_confirm_project_profile(project_id)

    def ignore_project(self, repo_path: str, reason: str = "") -> dict[str, Any]:
        """Add a project path to the ignore list."""
        return handle_ignore_project(repo_path, reason)

    def _execute(self, task: dict[str, Any], project: dict[str, Any], dry_run: bool = False) -> None:
        task_id = task["task_id"]
        gate = self.execution_gate.run(task, project)
        for transition in gate.transitions:
            self._set_status(task_id, transition.status, transition.event_type, transition.payload)
        if not gate.continue_execution:
            if gate.policy_incident:
                self._record_policy_learning(task, project, success=False, incident=True)
            return

        route = self.route_planner.route_for_task(task, project)
        route = apply_read_budget_to_route(route, task)
        self.artifacts.write_json(task_id, "route.json", route)
        self.db.update_task(
            task_id, route_worker=route["selected_worker"],
            route_model=route["selected_model"], route_variant=route.get("variant") or "", updated_at=_now(),
        )
        self._set_status(task_id, "ROUTED", "routed", route)

        preparation = self.preparation.prepare(
            task_id=task_id,
            task=task,
            project=project,
            route=route,
            dry_run=dry_run,
        )
        wt = preparation.worktree

        # ── Retry chain with escalation ──
        attempt_run = self.attempt_runner.run(
            task_id=task_id,
            task=task,
            route=route,
            worktree_path=Path(wt.path),
            dry_run=dry_run,
        )
        if attempt_run.terminal_status:
            self._set_status(task_id, attempt_run.terminal_status, attempt_run.terminal_event or "", attempt_run.terminal_payload)
        if not attempt_run.completed:
            if attempt_run.policy_signal:
                signal = attempt_run.policy_signal
                self._record_policy_learning(
                    task,
                    project,
                    success=signal.success,
                    worker=signal.worker,
                    model=signal.model,
                    rollback=signal.rollback,
                    incident=signal.incident,
                )
            return
        final_result = attempt_run.final_result
        last_attempt = attempt_run.last_attempt

        self.completion_pipeline.run(
            task_id=task_id,
            task=task,
            project=project,
            route=route,
            worker_result=final_result,
            last_attempt=last_attempt,
            worktree_path=Path(wt.path),
            branch=wt.branch,
            dry_run=dry_run,
        )

    def _record_policy_learning(
        self, task: dict[str, Any], project: dict[str, Any], success: bool,
        worker: str = "", model: str = "", variant: str = "",
        tests_passed: bool = False, codex_review_approved: bool = False,
        pr_created: bool = False, rollback: bool = False, incident: bool = False,
        changed_paths: list[str] | None = None,
    ) -> None:
        self.policy_learning.record_task_completion(
            task,
            project,
            success,
            worker=worker,
            model=model,
            variant=variant,
            tests_passed=tests_passed,
            codex_review_approved=codex_review_approved,
            pr_created=pr_created,
            rollback=rollback,
            incident=incident,
            changed_paths=changed_paths,
        )

    def _set_status(self, task_id: str, status: str, event_type: str, payload: dict[str, Any]) -> None:
        self.lifecycle.set_status(task_id, status, event_type, payload)

    def _check_worker_declared_permissions(self, task_id: str, worker_name: str, task: dict[str, Any]) -> dict[str, Any]:
        return self.permission_auditor.check_declared_permissions(task_id, worker_name, task)

    def _check_worker_diff_permissions(self, task_id: str, worker_name: str, changed_files: list[str]) -> dict[str, Any]:
        return self.permission_auditor.check_diff_permissions(task_id, worker_name, changed_files)

    def _write_attempt_metrics(
        self,
        task_id: str,
        attempt_no: int,
        attempt: dict[str, Any],
        worker_result: Any,
        failure: FailureClassification | None,
        build_passed: bool | None = None,
        review_approved: bool | None = None,
    ) -> None:
        self.attempt_metrics.write_attempt_metrics(
            task_id,
            attempt_no,
            attempt,
            worker_result,
            failure,
            build_passed=build_passed,
            review_approved=review_approved,
        )

    def _write_token_ledger(self, task_id: str) -> None:
        self.attempt_metrics.write_token_ledger(task_id)

    def _reap_stale_worker_task(self, task: dict[str, Any]) -> None:
        result = self.stale_worker_reaper.reap(task)
        if result:
            self._set_status(task["task_id"], result.status, result.event_type, result.payload)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _project_registration_health(project: dict[str, Any] | None, requested_repo_path: str | None = None) -> dict[str, Any]:
    if not project:
        return {"status": "unknown", "issues": ["project is not registered"], "warnings": []}
    issues: list[str] = []
    warnings: list[str] = []
    repo_raw = str(project.get("repo") or "")
    repo_path = Path(repo_raw).expanduser() if repo_raw else None
    if not repo_raw:
        issues.append("registered project has no repo path")
    elif not repo_path.exists():
        issues.append(f"registered repo path does not exist: {repo_raw}")
    requested = Path(requested_repo_path).expanduser().resolve() if requested_repo_path else None
    if requested and repo_path and repo_path.exists():
        try:
            if repo_path.resolve() != requested:
                issues.append(f"registered repo path differs from requested path: {repo_raw}")
        except OSError:
            issues.append(f"registered repo path cannot be resolved: {repo_raw}")
    if project.get("allow_auto_pr") is True:
        issues.append("allow_auto_pr is enabled; World deployment policy expects false unless explicitly approved")
    for key in ("test_commands", "build_commands"):
        value = project.get(key)
        if value is not None and not isinstance(value, list):
            issues.append(f"{key} must be a list")
        elif value == []:
            warnings.append(f"{key} is empty")
    return {
        "status": "needs_fix" if issues else "ok",
        "issues": issues,
        "warnings": warnings,
    }


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
