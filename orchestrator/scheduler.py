from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .baselines import build_manual_baseline, build_replay_baseline
from .codex_usage_recording import CodexUsageRecorder
from .config import ensure_runtime_dirs
from .constants import DEFAULT_CLAUDE_CMD, DEFAULT_OPENCODE_CMD
from .db import TaskDB
from .failure_classifier import (
    FailureClassification,
)
from .multimodal import load_image_inputs
from .pr import create_pr_or_patch
from .project_memory import ensure_project_memory
from .project_registry import detect_project, load_projects
from .task_protocol import (
    apply_read_budget_to_route,
    normalize_task_protocol,
)
from .task_artifact_repair import TaskArtifactRepairService
from .task_lifecycle import TaskLifecycleController
from .task_outcome_recording import TaskOutcomeRecorder
from .task_publish import TaskPublishRunner
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
from .risk_policy import evaluate_task
from .router import plan_route
from .read_only_completion import (
    read_only_result_can_finish as _read_only_result_can_finish,
    task_requires_diff as _task_requires_diff,
    task_requests_project_verification as _task_requests_project_verification,
)
from .runtime_store import RuntimeStore
from .task_routing import (
    apply_route_override as _apply_route_override,
    world_enabled as _world_enabled,
    world_write_policy as _world_write_policy,
)
from .stale_worker_reaper import StaleWorkerReaper
from .task_result_document import build_final_markdown as _final_md
from .task_review import TaskReviewRunner
from .terminal_handlers import TerminalTaskHandler
from .task_verification import TaskVerificationRunner
from .verifier import verify
from .agents_md import inject_agents_md
from .worktree import prepare_worktree
from .approval_graph import ApprovalGraph, ApprovalMode, _classify_task_type
from .approval_memory import ApprovalMemory
from .approval_explainer import explain_decision
from .attempt_recording import AttemptMetricsRecorder
from .policy_learning import PolicyLearningRecorder
from .policy_update_engine import PolicyUpdateEngine
from .post_attempt_policy import decide_post_attempt
from .process_control import request_cancel
from .worker_permission_audit import WorkerPermissionAuditor
from .worker_attempts import (
    build_retry_chain as _build_retry_chain,
)
from .worker_attempt_executor import WorkerAttemptExecutor
from .worker_prompt import build_worker_prompt
from .workers.claude_code_worker import ClaudeCodeWorker
from .workers.mimo_vision_adapter import MimoVisionAdapter
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
        self.stale_worker_reaper = StaleWorkerReaper(
            artifacts=self.artifacts,
            dry_verify_func=_dry_verify,
            task_requires_diff=_task_requires_diff,
        )
        self.policy_learning = PolicyLearningRecorder(self.db)

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
        """Bootstrap World for a repo without writing World core files into it."""
        store = RuntimeStore(repo_path, preferred_write_policy)  # type: ignore[arg-type]
        profile = self.profile_project(repo_path, force=False)
        detected = self.detect_project(repo_path=repo_path)
        orchestrator_project_id = detected.get("project_id")
        profile_payload = {
            "project_id": orchestrator_project_id,
            "runtime_id": store.project_id,
            "repo_path": str(Path(repo_path).expanduser().resolve()),
            "user_prompt": user_prompt,
            "profile": profile,
            "write_policy": preferred_write_policy,
            "world_runtime_mode": store.backend,
        }
        profile_path = store.write_project_profile(profile_payload)
        return {
            "world_enabled": True,
            "write_policy": preferred_write_policy,
            "runtime_backend": store.backend,
            "runtime_store": str(store.project_dir),
            "project_id": orchestrator_project_id,
            "runtime_id": store.project_id,
            "detect": detected,
            "project_profile_path": str(profile_path),
            "next_tool": "world_profile_project",
        }

    def world_profile_project(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        """World-named wrapper around the adaptive project profiler."""
        return self.profile_project(repo_path, force)

    def world_create_plan(
        self,
        repo_path: str,
        user_goal: str,
        risk_level: str = "medium",
        preferred_write_policy: str = "zero_write",
    ) -> dict[str, Any]:
        """Create a WorldPlan and write it to the external RuntimeStore."""
        store = RuntimeStore(repo_path, preferred_write_policy)  # type: ignore[arg-type]
        run_id = new_task_id().replace("t_", "world_", 1)
        profile = self.profile_project(repo_path, force=False)
        project = {
            "project_id": store.project_id,
            "repo": str(Path(repo_path).expanduser().resolve()),
            "stack": profile.get("profile", {}).get("detected_types", []) if isinstance(profile, dict) else [],
            "test_commands": profile.get("profile", {}).get("test_commands", []) if isinstance(profile, dict) else [],
            "build_commands": profile.get("profile", {}).get("build_commands", []) if isinstance(profile, dict) else [],
            "default_worker": "claude_code",
            "default_model": "deepseek_pro",
        }
        route = self._build_world_plan_route(user_goal, risk_level, project)
        plan = {
            "run_id": run_id,
            "project_id": store.project_id,
            "repo_path": str(Path(repo_path).expanduser().resolve()),
            "user_goal": user_goal,
            "risk_level": risk_level,
            "write_policy": preferred_write_policy,
            "runtime_backend": store.backend,
            "route": route,
            "safe_parallelism": _safe_parallelism_from_profile(profile),
            "worker_required": True,
            "final_review": "World Review",
        }
        plan_path = store.write_plan(run_id, plan)
        return {"plan": plan, "plan_path": str(plan_path), "runtime_store": str(store.project_dir)}

    def world_doctor(self, repo_path: str | None = None) -> dict[str, Any]:
        """World health check for RuntimeStore and worker command availability."""
        from .command_utils import command_available

        checks: list[dict[str, Any]] = []
        for label, command in {
            "git": "git",
            "claude": __import__("os").environ.get("AI_CLAUDE_CMD", DEFAULT_CLAUDE_CMD),
            "opencode": __import__("os").environ.get("AI_OPENCODE_CMD", DEFAULT_OPENCODE_CMD),
        }.items():
            ok, detail = command_available(command)
            checks.append({"name": f"{label} available", "ok": ok, "detail": detail})

        runtime: dict[str, Any] | None = None
        if repo_path:
            try:
                store = RuntimeStore(repo_path, "zero_write")
                runtime = {
                    "project_id": store.project_id,
                    "backend": store.backend,
                    "project_dir": str(store.project_dir),
                }
                checks.append({"name": "RuntimeStore available", "ok": True, "detail": str(store.project_dir)})
            except Exception as exc:
                checks.append({"name": "RuntimeStore available", "ok": False, "detail": str(exc)})

        status = "healthy" if all(c["ok"] for c in checks if c["name"] in {"git available", "RuntimeStore available"}) else "degraded"
        return {"status": status, "checks": checks, "runtime": runtime}

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
        protocol = normalize_task_protocol(
            user_goal,
            task_mode=task_mode,
            expected_diff=expected_diff,
            verification_policy=verification_policy,
            read_budget_profile=read_budget_profile,
            read_budget=read_budget,
        )
        memory_payload = ensure_project_memory(project_id, project)
        task = {
            "task_id": task_id,
            "project_id": project_id,
            "repo_path": project["repo"],
            "user_goal": user_goal,
            "risk_level": risk_level,
            "auto_execute": auto_execute,
            "auto_pr": bool(auto_pr and project.get("allow_auto_pr", False)),
            "auto_merge": False,
            "status": "QUEUED",
            "created_at": now,
            "updated_at": now,
            "run_dir": str(run_dir),
            "test_commands": project.get("test_commands", []),
            "build_commands": project.get("build_commands", []),
            "forbidden_paths": project.get("forbidden_paths", []),
            "image_paths": image_paths or [],
            "image_base64": image_base64 or [],
            "project_memory": memory_payload,
            **protocol,
        }
        if force_worker or force_model or force_variant:
            task["route_override"] = {
                "worker": force_worker,
                "model": force_model,
                "variant": force_variant,
            }
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
            protocol=protocol,
            project_memory=memory_payload,
            run_dir=str(run_dir),
        )
        if auto_execute:
            self._execute(task, project, dry_run=dry_run)
        return {"task_id": task_id, "status": self.get_task_status(task_id)["status"], "run_dir": str(run_dir)}

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self._reap_stale_worker_task(task)
        task = self.db.get_task(task_id) or task
        events = self.db.list_events(task_id)
        return {**task, "events": events[-10:]}

    def read_task_result(self, task_id: str, sections: list[str] | None = None) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self._reap_stale_worker_task(task)
        task = self.db.get_task(task_id) or task
        index = self.artifacts.index(task_id)
        result: dict[str, Any] = {"task": task, "artifacts": index}
        for key in ["final.md", "review/review.json", "verify/verify.json", "verify/diff.patch", "metrics.json", "token_ledger.json", "multimodal/vision_observation.json", "result.json"]:
            path = index.get(key)
            if path:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
                result[key] = text[:20000]
        return result

    def record_task_baseline(
        self,
        task_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        actual: bool = False,
        baseline_kind: str | None = None,
    ) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        if input_tokens is not None or output_tokens is not None:
            if input_tokens is None or output_tokens is None:
                return {"status": "INVALID_REQUEST", "error": "input_tokens and output_tokens must be provided together"}
            baseline = build_manual_baseline(
                task_id=task_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                baseline_kind=baseline_kind or ("codex_only_actual" if actual else "codex_only_manual_estimate"),
                actual_codex_used=actual,
                metadata={"source": "cli_record_task_baseline"},
            )
        else:
            baseline = build_replay_baseline(
                task=task,
                artifact_index=self.artifacts.index(task_id),
                baseline_kind=baseline_kind or "codex_only_replay",
            )
        self.db.record_task_baseline(baseline)
        self.artifacts.append_jsonl(task_id, "baselines/task_baselines.jsonl", baseline)
        self.db.append_event(
            task_id,
            "task_baseline_recorded",
            None,
            None,
            {
                "baseline_kind": baseline.get("baseline_kind"),
                "source": baseline.get("source"),
                "total_tokens": baseline.get("total_tokens"),
                "actual_codex_used": bool(baseline.get("actual_codex_used")),
            },
        )
        self._write_token_ledger(task_id)
        return {
            "status": "BASELINE_RECORDED",
            "task_id": task_id,
            "baseline": baseline,
            "token_ledger_path": str(Path(str(task["run_dir"])) / "token_ledger.json") if task.get("run_dir") else None,
        }

    def repair_task_artifacts(self, task_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return self.artifact_repair.repair_task_artifacts(task_id, limit)

    def open_task_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        return {"task_id": task_id, "run_dir": task["run_dir"], "files": self.artifacts.index(task_id)}

    def get_task_control(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self._reap_stale_worker_task(task)
        task = self.db.get_task(task_id) or task
        control_dir = Path(task["run_dir"]) / "control"
        return {
            "task_id": task_id,
            "task_status": task["status"],
            "run_dir": task["run_dir"],
            "control_dir": str(control_dir),
            "process": _read_json_if_exists(control_dir / "process.json"),
            "heartbeat": _read_json_if_exists(control_dir / "heartbeat.json"),
            "cancel_requested": _read_json_if_exists(control_dir / "cancel.requested"),
        }

    def cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        control = request_cancel(Path(task["run_dir"]), reason)
        self.db.update_task(task_id, status="CANCELLED", updated_at=_now())
        self.db.append_event(
            task_id,
            "cancelled",
            task["status"],
            "CANCELLED",
            {"reason": reason, "control": control},
        )
        return self.get_task_status(task_id)

    def rollback_task(self, task_id: str, cleanup_worktree: bool = True) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self.db.update_task(task_id, status="ROLLED_BACK", updated_at=_now())
        self.db.append_event(task_id, "rolled_back", task["status"], "ROLLED_BACK", {"cleanup_worktree": cleanup_worktree})
        # Record rollback for policy learning (demotes trust)
        self._record_policy_learning(
            task, {}, success=False,
            worker=task.get("route_worker", ""), model=task.get("route_model", ""),
            rollback=True,
        )
        return self.get_task_status(task_id)

    # ── Dynamic Approval Graph methods ──

    def get_approval_decision(self, project_id: str, user_goal: str, risk_level: str = "medium") -> dict[str, Any]:
        """Get the approval decision for a potential task without submitting it."""
        graph = ApprovalGraph(self.db)
        task = {"user_goal": user_goal, "risk_level": risk_level, "project_id": project_id}
        decision = graph.decide(task)
        return {"decision": decision.to_dict(), "explanation": explain_decision(decision, task)}

    def approve_task(self, task_id: str, user: str = "codex") -> dict[str, Any]:
        """User approves a task awaiting approval."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self._record_user_decision(task, "approved")
        return {"status": "approved", "task_id": task_id}

    def reject_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        """User rejects a task awaiting approval."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        self._record_user_decision(task, "rejected", reason)
        self.cancel_task(task_id, reason=f"User rejected: {reason}")
        return {"status": "rejected", "task_id": task_id}

    def list_learned_rules(self, project_id: str) -> dict[str, Any]:
        """List learned approval rules for a project."""
        mem = ApprovalMemory(self.db)
        rules = mem.get_learned_rules(project_id)
        from .approval_explainer import explain_learned_rules
        return {"rules": rules, "summary": explain_learned_rules(rules)}

    def revoke_learned_rule(self, pattern_id: int) -> dict[str, Any]:
        """Revoke (deactivate) a learned approval rule."""
        mem = ApprovalMemory(self.db)
        mem.revoke_rule(pattern_id)
        return {"status": "revoked", "pattern_id": pattern_id}

    def explain_approval(self, task_id: str) -> dict[str, Any]:
        """Explain the approval decision for an existing task."""
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        graph = ApprovalGraph(self.db)
        decision = graph.decide(task)
        return {"decision": decision.to_dict(), "explanation": explain_decision(decision, task)}

    def list_policy_suggestions(self, project_id: str) -> dict[str, Any]:
        """List pending policy suggestions for a project."""
        engine = PolicyUpdateEngine(self.db)
        suggestions = engine.generate_suggestions(project_id)
        return {"suggestions": suggestions, "count": len(suggestions)}

    def approve_policy_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """Approve a policy suggestion and create a matching override."""
        engine = PolicyUpdateEngine(self.db)
        return engine.approve_suggestion(suggestion_id, user="codex")

    def reject_policy_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """Reject a policy suggestion."""
        engine = PolicyUpdateEngine(self.db)
        return engine.reject_suggestion(suggestion_id)

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

    def _record_user_decision(self, task: dict[str, Any], decision: str, feedback: str = "") -> None:
        """Record a user's approve/reject decision for learning."""
        mem = ApprovalMemory(self.db)
        mem.record_outcome(
            task_id=task["task_id"],
            project_id=task.get("project_id", ""),
            task_type=task.get("task_type", _classify_task_type(task.get("user_goal", ""), {})),
            risk_level=task.get("risk_level", "medium"),
            approval_mode="HARD_APPROVAL",
            user_decision=decision,
            user_feedback=feedback,
        )

    def _execute(self, task: dict[str, Any], project: dict[str, Any], dry_run: bool = False) -> None:
        task_id = task["task_id"]
        task["task_type"] = _classify_task_type(task["user_goal"], project)

        # ── Static risk check ──
        risk = evaluate_task(task["user_goal"], task["risk_level"], task["auto_pr"], task["auto_merge"])
        self.artifacts.write_json(task_id, "risk.json", risk.__dict__)
        if not risk.allowed:
            self._set_status(task_id, "FAILED_FINAL", "risk_blocked", risk.__dict__)
            self._record_policy_learning(task, project, success=False, incident=True)
            return

        # ── Dynamic Approval Graph ──
        graph = ApprovalGraph(self.db)
        approval = graph.decide(task, project)
        self.artifacts.write_json(task_id, "approval.json", approval.to_dict())
        self._set_status(task_id, "CLASSIFIED", "classified", {"task_type": task["task_type"]})

        if approval.mode == ApprovalMode.BLOCKED:
            self._set_status(task_id, "BLOCKED", "approval_blocked", approval.to_dict())
            return
        self._set_status(task_id, "DYNAMIC_RISK_SCORED", "risk_scored", {"risk_score": approval.risk_score})
        self._set_status(task_id, "APPROVAL_DECIDED", "approval_decided", approval.to_dict())

        if approval.mode == ApprovalMode.HARD_APPROVAL:
            self._set_status(task_id, "HARD_APPROVAL_WAITING", "awaiting_hard_approval", approval.to_dict())
            self.artifacts.write_text(task_id, "approval_explanation.md", explain_decision(approval, task))
            return
        elif approval.mode == ApprovalMode.SOFT_APPROVAL:
            self._set_status(task_id, "SOFT_APPROVAL_WAITING", "awaiting_soft_approval", approval.to_dict())
        elif approval.mode == ApprovalMode.AUTO_SILENT:
            self._set_status(task_id, "AUTO_SILENT", "auto_silent", approval.to_dict())
        elif approval.mode == ApprovalMode.AUTO_WITH_SUMMARY:
            self._set_status(task_id, "AUTO_WITH_SUMMARY", "auto_with_summary", approval.to_dict())

        route = self._route_for_task(task, project)
        route = apply_read_budget_to_route(route, task)
        self.artifacts.write_json(task_id, "route.json", route)
        self.db.update_task(
            task_id, route_worker=route["selected_worker"],
            route_model=route["selected_model"], route_variant=route.get("variant") or "", updated_at=_now(),
        )
        self._set_status(task_id, "ROUTED", "routed", route)

        wt = prepare_worktree(
            project["repo"], project.get("default_branch", "main"),
            task_id, Path(task["run_dir"]), dry_run=dry_run,
        )
        self.artifacts.write_json(task_id, "worktree.json", wt.__dict__)
        task["worktree_path"] = wt.path
        self._set_status(task_id, "WORKTREE_READY", "worktree_ready", wt.__dict__)

        if task.get("image_paths") or task.get("image_base64"):
            observation = self._run_mimo_vision(task, dry_run=dry_run)
            task["vision_observation"] = observation
            task["vision_observation_path"] = str(Path(task["run_dir"]) / "multimodal" / "vision_observation.json")
            self.artifacts.write_json(task_id, "task.json", task)
            self._set_status(task_id, "WORKTREE_READY", "vision_observation_ready", {
                "path": task["vision_observation_path"],
                "degraded": observation.get("degraded", False),
                "confidence": observation.get("confidence"),
            })

        # ── Inject AGENTS.md for OpenCodeWorker (skip if user file exists) ──
        if route.get("selected_worker") == "opencode":
            agents_inject = inject_agents_md(Path(wt.path))
            self.artifacts.write_json(task_id, "agents_md.json", agents_inject.__dict__)
            if not agents_inject.injected:
                self._set_status(task_id, "WORKTREE_READY", "agents_md_skipped", agents_inject.__dict__)

        # ── Retry chain with escalation ──
        retry_chain = _build_retry_chain(route, task)
        final_result = None
        verify_result = None
        review = None
        last_failure: FailureClassification | None = None
        last_attempt: dict[str, Any] | None = None

        for idx, attempt in enumerate(retry_chain):
            attempt = apply_read_budget_to_route(attempt, task)
            outcome = self.attempt_executor.run(
                task_id=task_id,
                task=task,
                worktree_path=Path(wt.path),
                attempt=attempt,
                attempt_no=idx + 1,
                dry_run=dry_run,
            )
            attempt = outcome.attempt
            worker_result = outcome.worker_result
            failure = outcome.failure

            if outcome.kind == "preflight_denied":
                self._set_status(
                    task_id,
                    "BLOCKED",
                    "permission_denied",
                    {"phase": "preflight", "permission": outcome.permission, "failure": failure.to_dict() if failure else None},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return
            if outcome.kind == "preflight_requires_ask":
                self._set_status(
                    task_id,
                    "HARD_APPROVAL_WAITING",
                    "permission_requires_approval",
                    {"phase": "preflight", "permission": outcome.permission},
                )
                self.artifacts.write_text(
                    task_id,
                    "approval_explanation.md",
                    "Static worker permissions require explicit approval for declared write paths.\n",
                )
                return
            if outcome.kind == "worker_exception":
                self._set_status(
                    task_id,
                    "FAILED_FINAL",
                    "worker_exception",
                    {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "attempt": idx + 1},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return
            if outcome.kind == "diff_denied":
                self._set_status(
                    task_id,
                    "BLOCKED",
                    "permission_denied",
                    {"phase": "diff", "permission": outcome.permission, "failure": failure.to_dict() if failure else None},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return
            if outcome.kind == "diff_requires_ask":
                self._set_status(
                    task_id,
                    "HARD_APPROVAL_WAITING",
                    "permission_requires_approval",
                    {"phase": "diff", "permission": outcome.permission},
                )
                return
            if outcome.kind != "completed" or worker_result is None:
                self._set_status(
                    task_id,
                    "FAILED_FINAL",
                    "worker_unknown_attempt_outcome",
                    {"attempt": idx + 1, "kind": outcome.kind},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return

            if failure:
                last_failure = failure
                last_attempt = attempt

            decision = decide_post_attempt(
                task=task,
                worker_result=worker_result,
                failure=failure,
                attempt=attempt,
                attempt_index=idx,
                retry_chain=retry_chain,
                dry_run=dry_run,
                worker_name=WORKERS.get(attempt["worker"], WORKERS["claude_code"]).name,
            )

            if decision.kind == "success":
                final_result = worker_result
                last_attempt = attempt
                break

            if decision.kind == "no_diff":
                failure = decision.failure
                last_failure = failure
                last_attempt = attempt
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                self._write_attempt_metrics(task_id, idx + 1, attempt, worker_result, failure)
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                if idx + 1 < len(retry_chain):
                    continue
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], rollback=True)
                return

            if decision.kind == "recover_failed_diff":
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                final_result = worker_result
                last_attempt = attempt
                break

            if decision.kind == "blocked":
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return

            if decision.kind == "cancelled":
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                return

            if decision.kind == "non_retryable_failure":
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return

            if decision.kind == "retry":
                self._set_status(task_id, decision.status, decision.event_type, decision.payload or {})
                continue

        # ── All attempts exhausted ──
        if not final_result:
            payload = {"total_attempts": len(retry_chain)}
            if last_failure:
                payload.update({"failure_reason": last_failure.failure_reason, "failure": last_failure.to_dict()})
            if last_attempt:
                payload["last_attempt"] = {
                    "worker": last_attempt.get("worker"),
                    "model": last_attempt.get("model"),
                    "attempt": last_attempt.get("attempt_no"),
                }
            self._set_status(task_id, "FAILED_FINAL", "all_attempts_failed", payload)
            self._record_policy_learning(task, project, success=False, worker=retry_chain[-1]["worker"], model=retry_chain[-1]["model"], rollback=True)
            return

        if _worker_result_is_degraded_mock(final_result):
            terminal = self.terminal_handler.handle_degraded_mock(
                task_id=task_id,
                task=task,
                route=route,
                worker_result=final_result,
                last_attempt=last_attempt,
                dry_run=dry_run,
            )
            self._set_status(task_id, terminal.status, terminal.event_type, terminal.payload)
            self._record_policy_learning(
                task,
                project,
                success=terminal.policy_success,
                worker=route["selected_worker"],
                model=route["selected_model"],
            )
            return

        # ── Verify ──
        self._set_status(task_id, "VERIFYING", "verify_started", {})
        verification = self.verification_runner.run(
            task_id=task_id,
            task=task,
            worktree_path=Path(wt.path),
            worker_result=final_result,
            last_attempt=last_attempt,
            dry_run=dry_run,
        )
        verify_result = verification.verify_result
        forbidden = verification.forbidden

        if not verification.passed:
            failure = verification.failure
            assert failure is not None
            if last_attempt:
                self._write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    final_result,
                    failure,
                    build_passed=verify_result.build_passed,
                )
            self._set_status(task_id, "FAILED_FINAL", "verify_failed",
                             {"failure_reason": failure.failure_reason, "failure": failure.to_dict(),
                              "verify": verify_result.to_dict(), "forbidden": forbidden.__dict__})
            self._record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return

        if _read_only_result_can_finish(task, final_result):
            terminal = self.terminal_handler.handle_read_only_completion(
                task_id=task_id,
                task=task,
                route=route,
                worker_result=final_result,
                verify_result=verify_result,
                forbidden=forbidden,
                last_attempt=last_attempt,
                dry_run=dry_run,
            )
            self._set_status(task_id, terminal.status, terminal.event_type, terminal.payload)
            self._record_policy_learning(
                task,
                project,
                success=terminal.policy_success,
                worker=route["selected_worker"],
                model=route["selected_model"],
                tests_passed=terminal.tests_passed,
                codex_review_approved=terminal.codex_review_approved,
                changed_paths=terminal.changed_paths or [],
            )
            return

        # ── Review ──
        self._set_status(task_id, "CODEX_REVIEWING", "review_started", {})
        review_outcome = self.review_runner.run(
            task_id=task_id,
            task=task,
            verify_result=verify_result,
            forbidden=forbidden,
            dry_run=dry_run,
        )
        review = review_outcome.review
        if review_outcome.degraded_blocks_publish:
            failure = review_outcome.failure
            assert failure is not None
            if last_attempt:
                self._write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    final_result,
                    failure,
                    build_passed=verify_result.build_passed,
                    review_approved=False,
                )
            self.artifacts.write_text(task_id, "final.md", _final_md(task, route, final_result.__dict__, verify_result.to_dict(), review))
            self._set_status(task_id, "NEEDS_REVIEW", "review_degraded_needs_review",
                             {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "review": review})
            self._record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return
        if not review_outcome.passed:
            failure = review_outcome.failure
            assert failure is not None
            if last_attempt:
                self._write_attempt_metrics(
                    task_id,
                    int(last_attempt.get("attempt_no", 1)),
                    last_attempt,
                    final_result,
                    failure,
                    build_passed=verify_result.build_passed,
                    review_approved=False,
                )
            self._set_status(task_id, "FAILED_FINAL", "review_failed",
                             {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "review": review})
            self._record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return
        if last_attempt:
            self._write_attempt_metrics(
                task_id,
                int(last_attempt.get("attempt_no", 1)),
                last_attempt,
                final_result,
                None,
                build_passed=verify_result.build_passed,
                review_approved=True,
            )

        # ── Policy Learning ──
        self._set_status(task_id, "POLICY_LEARNING", "policy_learning", {})
        self._record_policy_learning(
            task, project, success=True,
            worker=route["selected_worker"], model=route["selected_model"],
            tests_passed=verify_result.tests_passed,
            codex_review_approved=review.get("approved", False),
            changed_paths=verify_result.changed_files,
        )

        # ── PR / Patch ──
        self._set_status(task_id, "PLANNED", "review_passed", review)
        final = _final_md(task, route, final_result.__dict__, verify_result.to_dict(), review)
        self.artifacts.write_text(task_id, "final.md", final)

        publish = self.publish_runner.run(
            task_id=task_id,
            task=task,
            project=project,
            worktree_path=Path(wt.path),
            branch=wt.branch,
        )
        self._set_status(task_id, publish.status, publish.event_type, publish.payload)
        if publish.pr_created:
            self._record_policy_learning(task, project, success=True, worker=route["selected_worker"],
                                         model=route["selected_model"], pr_created=True)

    def _route_for_task(self, task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        """Return the canonical route for a task.

        World-enabled projects must route through WorldPlan first so submit-task,
        world-create-plan, and MCP entrypoints share the same decision source.
        """
        if _world_enabled(project):
            plan_result = self.world_create_plan(
                project["repo"],
                task["user_goal"],
                task.get("risk_level", "medium"),
                _world_write_policy(project),
            )
            task_id = task["task_id"]
            route = apply_read_budget_to_route(_apply_route_override(dict(plan_result["plan"]["route"]), task), task)
            plan_result["plan"]["route"] = route
            plan_result["plan"]["task_mode"] = task.get("task_mode")
            plan_result["plan"]["expected_diff"] = task.get("expected_diff")
            plan_result["plan"]["verification_policy"] = task.get("verification_policy")
            plan_result["plan"]["read_budget_profile"] = task.get("read_budget_profile")
            plan_result["plan"]["read_budget"] = task.get("read_budget")
            self.artifacts.write_json(task_id, "world_plan.json", plan_result["plan"])
            self.artifacts.write_json(
                task_id,
                "world_plan_ref.json",
                {
                    "plan_path": plan_result["plan_path"],
                    "runtime_store": plan_result["runtime_store"],
                },
            )
            return route
        return _apply_route_override(plan_route(task, project, history=self.db.model_metrics_summary()).to_dict(), task)

    def _run_mimo_vision(self, task: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        images = load_image_inputs(task.get("image_paths"), task.get("image_base64"))
        adapter = MimoVisionAdapter()
        observation = adapter.analyze(
            task_id=task["task_id"],
            prompt=task["user_goal"],
            images=images,
            output_path=Path(task["run_dir"]) / "multimodal" / "vision_observation.json",
            model_key="mimo_v25",
            dry_run=dry_run,
        )
        return observation.to_dict()

    def _build_world_plan_route(self, user_goal: str, risk_level: str, project: dict[str, Any]) -> dict[str, Any]:
        return plan_route(
            {"user_goal": user_goal, "risk_level": risk_level},
            project,
            history=self.db.model_metrics_summary(),
        ).to_dict()

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


def _worker_result_is_degraded_mock(result: Any) -> bool:
    return bool(getattr(result, "mock_result", False) or getattr(result, "degraded", False))


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"unreadable": str(path)}


def _safe_parallelism_from_profile(profile: dict[str, Any]) -> int:
    """Extract safe_parallelism from profiler output with conservative fallback."""
    if not isinstance(profile, dict):
        return 1
    nested = profile.get("profile")
    if isinstance(nested, dict) and isinstance(nested.get("safe_parallelism"), int):
        return max(1, int(nested["safe_parallelism"]))
    if isinstance(profile.get("safe_parallelism"), int):
        return max(1, int(profile["safe_parallelism"]))
    detected = []
    if isinstance(nested, dict):
        detected = [str(x).lower() for x in nested.get("detected_types", [])]
    if any(x in detected for x in ["unity", "android_gradle", "java"]):
        return 1
    if any(x in detected for x in ["node", "react", "vite", "python"]):
        return 2
    return 1


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
