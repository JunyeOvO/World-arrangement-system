from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .config import code_root, ensure_runtime_dirs
from .constants import DEFAULT_CLAUDE_CMD, DEFAULT_OPENCODE_CMD
from .db import TaskDB
from .failure_classifier import (
    FailureClassification,
    classify_review_failure,
    classify_verify_failure,
    classify_worker_failure,
)
from .metrics import collect_task_metrics, write_metrics
from .permissions import check_write_paths
from .pr import create_pr_or_patch
from .project_registry import detect_project, load_projects
from .project_commands import (
    handle_batch_discover_and_register,
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
from .risk_policy import check_changed_files, evaluate_task
from .router import plan_route
from .agent_llm import agent_llm_name
from .llm_capability import capability_profile, normalize_capability_tier
from .runtime_store import RuntimeStore
from .verifier import verify, write_verify_result
from .agents_md import inject_agents_md
from .worktree import prepare_worktree
from .approval_graph import ApprovalGraph, ApprovalMode, _classify_task_type
from .approval_memory import ApprovalMemory
from .approval_explainer import explain_decision
from .policy_update_engine import PolicyUpdateEngine
from .process_control import request_cancel
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

    def list_projects(self, query: str | None = None) -> dict[str, Any]:
        projects = load_projects()
        rows = list(projects.values())
        if query:
            q = query.lower()
            rows = [p for p in rows if q in p.get("project_id", "").lower() or q in p.get("name", "").lower()]
        return {"projects": rows}

    def detect_project(self, repo_path: str | None = None, git_remote_url: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        match = detect_project(repo_path=repo_path, git_remote_url=git_remote_url, cwd=cwd)
        return {
            "project_id": match.project_id,
            "confidence": match.confidence,
            "matched_by": match.matched_by,
            "needs_user": match.needs_user,
            "project": match.project,
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
        profile_payload = {
            "project_id": store.project_id,
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
            "project_id": store.project_id,
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
    ) -> dict[str, Any]:
        match = detect_project(repo_path=repo_path or ".")
        if match.needs_user or not match.project_id:
            return {"status": "NEEDS_USER", "message": "project could not be detected", "match": match.__dict__}
        return self.submit_task(match.project_id, user_goal, risk_level, auto_execute, auto_pr, dry_run)

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
    ) -> dict[str, Any]:
        projects = load_projects()
        if project_id not in projects:
            return {"status": "NEEDS_USER", "message": f"unknown project_id: {project_id}"}
        project = projects[project_id]
        task_id = new_task_id()
        run_dir = self.artifacts.run_dir(task_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
        if auto_execute:
            self._execute(task, project, dry_run=dry_run)
        return {"task_id": task_id, "status": self.get_task_status(task_id)["status"], "run_dir": str(run_dir)}

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        events = self.db.list_events(task_id)
        return {**task, "events": events[-10:]}

    def read_task_result(self, task_id: str, sections: list[str] | None = None) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        index = self.artifacts.index(task_id)
        result: dict[str, Any] = {"task": task, "artifacts": index}
        for key in ["final.md", "review/review.json", "verify/verify.json", "verify/diff.patch", "metrics.json", "result.json"]:
            path = index.get(key)
            if path:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
                result[key] = text[:20000]
        return result

    def open_task_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
        return {"task_id": task_id, "run_dir": task["run_dir"], "files": self.artifacts.index(task_id)}

    def get_task_control(self, task_id: str) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            return {"status": "NOT_FOUND", "task_id": task_id}
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
            attempt_dir = Path(task["run_dir"]) / "attempts" / f"{idx + 1:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            attempt["attempt_no"] = idx + 1
            attempt["started_at"] = _now()

            worker = WORKERS.get(attempt["worker"], ClaudeCodeWorker())
            preflight = self._check_worker_declared_permissions(task_id, attempt["worker"], task)
            if not preflight["allowed"]:
                failure = FailureClassification(
                    "forbidden_path",
                    False,
                    "block_and_surface_policy_violation",
                    [item["reason"] for item in preflight.get("denied", [])],
                )
                self._set_status(
                    task_id,
                    "BLOCKED",
                    "permission_denied",
                    {"phase": "preflight", "permission": preflight, "failure": failure.to_dict()},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return
            if preflight["requires_ask"]:
                self._set_status(
                    task_id,
                    "HARD_APPROVAL_WAITING",
                    "permission_requires_approval",
                    {"phase": "preflight", "permission": preflight},
                )
                self.artifacts.write_text(
                    task_id,
                    "approval_explanation.md",
                    "Static worker permissions require explicit approval for declared write paths.\n",
                )
                return

            # ── Idempotent AGENTS.md injection before each OpenCode attempt ──
            # Covers prime=opencode AND ClaudeCodeWorker→OpenCodeWorker escalation.
            # Never overwrites an existing AGENTS.md (user file or prior injection).
            if attempt["worker"] == "opencode":
                attempt_inject = inject_agents_md(Path(wt.path))
                self.artifacts.write_json(
                    task_id, f"attempts/{idx + 1:02d}/agents_md.json", attempt_inject.__dict__,
                )
                if not attempt_inject.injected:
                    self._set_status(task_id, "EXECUTING", "agents_md_skipped", attempt_inject.__dict__)

            self._set_status(task_id, "EXECUTING", "worker_started", {
                "worker": attempt["worker"], "model": attempt["model"],
                "attempt": idx + 1, "variant": attempt.get("variant"),
            })

            prompt = _worker_prompt(task, {"selected_model": attempt["model"], "selected_worker": attempt["worker"]})
            task_for_worker = {**task, "task_id": task_id}
            worker_result = worker.run(prompt, Path(wt.path), attempt, task_for_worker, dry_run=dry_run)
            diff_permissions = self._check_worker_diff_permissions(task_id, attempt["worker"], worker_result.changed_files)
            if not diff_permissions["allowed"]:
                failure = FailureClassification(
                    "forbidden_path",
                    False,
                    "block_and_surface_policy_violation",
                    [item["reason"] for item in diff_permissions.get("denied", [])],
                )
                worker_result.status = "blocked"
                worker_result.risks.extend([item["reason"] for item in diff_permissions.get("denied", [])])
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                self._set_status(
                    task_id,
                    "BLOCKED",
                    "permission_denied",
                    {"phase": "diff", "permission": diff_permissions, "failure": failure.to_dict()},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return
            if diff_permissions["requires_ask"]:
                self._set_status(
                    task_id,
                    "HARD_APPROVAL_WAITING",
                    "permission_requires_approval",
                    {"phase": "diff", "permission": diff_permissions},
                )
                return

            attempt["finished_at"] = _now()
            attempt["status"] = worker_result.status
            attempt["summary"] = worker_result.summary
            failure = None
            if worker_result.status != "success":
                failure = classify_worker_failure(
                    status=worker_result.status,
                    summary=worker_result.summary,
                    risks=worker_result.risks,
                    changed_files=worker_result.changed_files,
                    stdout_path=worker_result.stdout_path,
                    stderr_path=worker_result.stderr_path,
                )
                attempt["failure_reason"] = failure.failure_reason
                attempt["failure"] = failure.to_dict()
                last_failure = failure
                last_attempt = attempt
            self.artifacts.write_json(task_id, f"attempts/{idx + 1:02d}/result.json", attempt)
            self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
            self._write_attempt_metrics(task_id, idx + 1, attempt, worker_result, failure)

            if worker_result.status == "success":
                if not dry_run and _task_requires_diff(task) and not worker_result.changed_files:
                    worker_result.status = "failed"
                    worker_result.summary = f"{worker.name} completed without producing a diff"
                    worker_result.risks.append("worker_no_diff")
                    failure = classify_worker_failure(
                        status=worker_result.status,
                        summary=worker_result.summary,
                        risks=worker_result.risks,
                        changed_files=worker_result.changed_files,
                        stdout_path=worker_result.stdout_path,
                        stderr_path=worker_result.stderr_path,
                    )
                    last_failure = failure
                    last_attempt = attempt
                    self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                    self._write_attempt_metrics(task_id, idx + 1, attempt, worker_result, failure)
                    self._set_status(
                        task_id,
                        "RETRYING" if idx + 1 < len(retry_chain) else "FAILED_FINAL",
                        "worker_no_diff",
                        {**worker_result.__dict__, "failure": failure.to_dict()},
                    )
                    if idx + 1 < len(retry_chain):
                        continue
                    self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], rollback=True)
                    return
                final_result = worker_result
                last_attempt = attempt
                break

            if _should_recover_failed_worker_diff(worker_result):
                worker_result.risks.append("scheduler_recover_failed_worker_diff")
                self.artifacts.write_json(task_id, "result.json", worker_result.__dict__)
                self._set_status(
                    task_id,
                    "EXECUTING",
                    "worker_failed_with_diff",
                    {**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
                )
                final_result = worker_result
                last_attempt = attempt
                break

            if worker_result.status == "blocked":
                # Non-retryable: safety violation, forbidden path, GLM rejection
                self._set_status(
                    task_id,
                    "BLOCKED",
                    "worker_blocked",
                    {**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return

            # Retryable failure — try next in chain
            if worker_result.status == "cancelled":
                self._set_status(
                    task_id,
                    "CANCELLED",
                    "worker_cancelled",
                    {**worker_result.__dict__, "failure": failure.to_dict() if failure else None},
                )
                return

            if failure and not failure.retryable:
                self._set_status(
                    task_id,
                    "FAILED_FINAL",
                    "worker_non_retryable_failure",
                    {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "attempt": idx + 1},
                )
                self._record_policy_learning(task, project, success=False, worker=attempt["worker"], model=attempt["model"], incident=True)
                return

            if idx + 1 < len(retry_chain):
                next_attempt = retry_chain[idx + 1]
                self._set_status(task_id, "RETRYING", "worker_retry", {
                    "failed_attempt": idx + 1, "failed_worker": attempt["worker"],
                    "next_worker": next_attempt["worker"], "next_model": next_attempt["model"],
                    "reason": failure.failure_reason if failure else attempt.get("reason", "worker_failed"),
                    "failure": failure.to_dict() if failure else None,
                })
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

        # ── Verify ──
        self._set_status(task_id, "VERIFYING", "verify_started", {})
        verify_result = verify(
            Path(wt.path), task.get("test_commands", []),
            task.get("build_commands", []),
            Path(task["run_dir"]) / "verify",
        ) if not dry_run else _dry_verify(task)
        forbidden = check_changed_files(verify_result.changed_files, task.get("forbidden_paths"))
        verify_result.forbidden_allowed = forbidden.allowed
        write_verify_result(verify_result, Path(task["run_dir"]) / "verify" / "verify.json")
        self.artifacts.write_json(task_id, "verify/changed_files.json", verify_result.changed_files)

        if not verify_result.tests_passed or not verify_result.build_passed or not forbidden.allowed:
            failure = classify_verify_failure(
                tests_passed=verify_result.tests_passed,
                build_passed=verify_result.build_passed,
                forbidden_allowed=forbidden.allowed,
                evidence=forbidden.blocking_issues,
            )
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

        # ── Review ──
        self._set_status(task_id, "CODEX_REVIEWING", "review_started", {})
        review = run_codex_review(
            {"task_id": task_id, "risk_level": task["risk_level"], "dry_run": dry_run,
             "tests_passed": verify_result.tests_passed, "forbidden_paths_touched": not forbidden.allowed,
             "changed_files": verify_result.changed_files},
            Path(task["run_dir"]) / "review" / "review.json",
        )
        if _review_degraded_blocks_publish(task, review):
            failure = classify_review_failure({**review, "available": False})
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
            self._set_status(task_id, "NEEDS_USER", "review_degraded_needs_user",
                             {"failure_reason": failure.failure_reason, "failure": failure.to_dict(), "review": review})
            self._record_policy_learning(task, project, success=False, worker=route["selected_worker"], model=route["selected_model"])
            return
        if not review.get("approved"):
            failure = classify_review_failure(review)
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

        allow_push = project.get("allow_remote_push", False)
        publish_result = create_pr_or_patch(
            Path(wt.path), wt.branch,
            project.get("pr_base_branch", project.get("default_branch", "main")),
            f"[ai-orchestrator] {task['user_goal'][:60]}",
            Path(task["run_dir"]) / "final.md",
            Path(task["run_dir"]) / "verify" / "diff.patch",
            allow_remote_push=allow_push,
        )
        self.artifacts.write_json(task_id, "publish.json", publish_result.__dict__)
        if publish_result.status == "PR_CREATED":
            self.db.update_task(task_id, pr_url=publish_result.pr_url, updated_at=_now())
            self._set_status(task_id, "PR_CREATED", "pr_created", publish_result.__dict__)
            self._record_policy_learning(task, project, success=True, worker=route["selected_worker"],
                                         model=route["selected_model"], pr_created=True)
        elif publish_result.status == "COMPLETED_WITH_PATCH":
            self._set_status(task_id, "COMPLETED_WITH_PATCH", "completed_with_patch", publish_result.__dict__)
        else:
            self._set_status(task_id, "DONE", "completed_without_publish", publish_result.__dict__)

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
            self.artifacts.write_json(task_id, "world_plan.json", plan_result["plan"])
            self.artifacts.write_json(
                task_id,
                "world_plan_ref.json",
                {
                    "plan_path": plan_result["plan_path"],
                    "runtime_store": plan_result["runtime_store"],
                },
            )
            return _apply_route_override(dict(plan_result["plan"]["route"]), task)
        return _apply_route_override(plan_route(task, project, history=self.db.model_metrics_summary()).to_dict(), task)

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
        """Record task outcome for policy learning (only from real results)."""
        engine = PolicyUpdateEngine(self.db)
        engine.on_task_complete(
            task_id=task["task_id"],
            project_id=task["project_id"],
            task_type=task.get("task_type", "routine_coding"),
            risk_level=task.get("risk_level", "medium"),
            approval_mode=task.get("status", "UNKNOWN"),
            worker=worker, model=model, variant=variant,
            planned_files_count=len(changed_paths or []),
            actual_files_count=len(changed_paths or []),
            changed_paths=changed_paths or [],
            tests_passed=tests_passed,
            codex_review_approved=codex_review_approved,
            pr_created=pr_created,
            rollback=rollback,
            incident=incident,
        )

    def _set_status(self, task_id: str, status: str, event_type: str, payload: dict[str, Any]) -> None:
        old = self.db.get_task(task_id)
        old_status = old["status"] if old else None
        self.db.update_task(task_id, status=status, updated_at=_now())
        self.db.append_event(task_id, event_type, old_status, status, payload)

    def _check_worker_declared_permissions(self, task_id: str, worker_name: str, task: dict[str, Any]) -> dict[str, Any]:
        paths = _declared_write_paths(task)
        review = check_write_paths(worker_name, paths).to_dict()
        self.db.append_event(
            task_id,
            "permission_preflight",
            self.db.get_task(task_id)["status"],
            self.db.get_task(task_id)["status"],
            {"worker": worker_name, "paths": paths, "permission": review},
        )
        return review

    def _check_worker_diff_permissions(self, task_id: str, worker_name: str, changed_files: list[str]) -> dict[str, Any]:
        review = check_write_paths(worker_name, changed_files or []).to_dict()
        event_type = "permission_denied" if not review["allowed"] else "permission_diff_checked"
        task = self.db.get_task(task_id)
        self.db.append_event(
            task_id,
            event_type,
            task["status"] if task else None,
            task["status"] if task else None,
            {"worker": worker_name, "changed_files": changed_files or [], "permission": review},
        )
        return review

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
        metrics = collect_task_metrics(
            task_id=task_id,
            attempt_no=attempt_no,
            worker=str(attempt.get("worker", "")),
            model=str(attempt.get("model", "")),
            status=str(getattr(worker_result, "status", "")),
            stream_path=getattr(worker_result, "stdout_path", None),
            changed_files_count=len(getattr(worker_result, "changed_files", []) or []),
            failure_reason=failure.failure_reason if failure else None,
            build_passed=build_passed,
            review_approved=review_approved,
        )
        metrics_path = Path(self.db.get_task(task_id)["run_dir"]) / "attempts" / f"{attempt_no:02d}" / "metrics.json"
        write_metrics(metrics, metrics_path)
        write_metrics(metrics, Path(self.db.get_task(task_id)["run_dir"]) / "metrics.json")
        self.db.upsert_task_metrics(metrics.to_dict())


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _declared_write_paths(task: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("owned_paths", "target_paths", "planned_files"):
        value = task.get(key)
        if isinstance(value, list):
            paths.extend(str(item) for item in value if item)
    return list(dict.fromkeys(paths))


def _review_degraded_blocks_publish(task: dict[str, Any], review: dict[str, Any]) -> bool:
    if not review.get("degraded"):
        return False
    return str(task.get("risk_level", "medium")).lower() in {"medium", "high", "max"}


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


def _world_enabled(project: dict[str, Any]) -> bool:
    world = project.get("world")
    if isinstance(world, dict) and world.get("enabled") is True:
        return True
    return project.get("world_enabled") is True


def _world_write_policy(project: dict[str, Any]) -> str:
    world = project.get("world")
    if isinstance(world, dict) and world.get("write_policy"):
        return str(world["write_policy"])
    return str(project.get("world_write_policy") or "zero_write")


def _apply_route_override(route: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    override = task.get("route_override")
    if not isinstance(override, dict):
        return route

    worker = override.get("worker") or route.get("selected_worker")
    model = override.get("model") or route.get("selected_model")
    variant = override.get("variant") if override.get("variant") is not None else route.get("variant")
    tier = normalize_capability_tier(variant, route.get("intensity"))
    profile = capability_profile(model, tier, route.get("intensity"))
    if worker == "opencode" and variant in {"high", "max"}:
        profile = capability_profile(model, variant, variant)

    route.update(
        {
            "selected_worker": worker,
            "selected_agent": worker,
            "selected_model": model,
            "selected_llm": model,
            "agent_llm": agent_llm_name(worker, model),
            "variant": variant,
            "capability_tier": profile.get("tier", tier),
            "capability_profile": profile,
            "reason": f"route override: worker={worker}, model={model}, variant={variant}",
            "fallback_models": [],
            "max_retries": 0,
            "escalation_policy": "none",
            "blocked": False,
            "retry_chain": [
                {
                    "worker": worker,
                    "model": model,
                    "variant": variant,
                    "intensity": profile.get("effort") or route.get("intensity"),
                    "capability_tier": profile.get("tier", tier),
                    "capability_profile": profile,
                    "reason": "route override primary attempt",
                }
            ],
        }
    )
    return route


def _build_retry_chain(route: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the retry chain from a route's escalation plan.

    Chain: primary attempt → fallback attempts → Codex review / NEEDS_USER.
    """
    route_retry_chain = route.get("retry_chain")
    if isinstance(route_retry_chain, list) and route_retry_chain:
        chain = []
        for idx, item in enumerate(route_retry_chain):
            if not isinstance(item, dict):
                continue
            model = item.get("model") or item.get("selected_model") or "deepseek_pro"
            worker = item.get("worker") or item.get("selected_worker") or "claude_code"
            tier = normalize_capability_tier(item.get("capability_tier"), item.get("intensity"))
            chain.append({
                "worker": worker,
                "model": model,
                "variant": item.get("variant"),
                "capability_tier": tier,
                "capability_profile": item.get("capability_profile")
                or capability_profile(model, tier, item.get("intensity")),
                "reason": item.get("reason") or ("primary attempt" if idx == 0 else item.get("condition", "route retry")),
                "status": "",
            })
        if chain:
            return chain

    chain: list[dict[str, Any]] = [
        {
            "worker": route.get("selected_worker", "claude_code"),
            "model": route.get("selected_model", "deepseek_pro"),
            "variant": route.get("variant"),
            "capability_tier": route.get("capability_tier"),
            "capability_profile": route.get("capability_profile"),
            "reason": "primary attempt",
            "status": "",
        }
    ]

    fallback_models = route.get("fallback_models", [])
    if isinstance(fallback_models, list):
        for fm in fallback_models:
            if isinstance(fm, str):
                tier = normalize_capability_tier(None, "medium")
                chain.append({"worker": "claude_code", "model": fm, "variant": None,
                              "capability_tier": tier,
                              "capability_profile": capability_profile(fm, tier, "medium"),
                              "reason": f"fallback to {fm}", "status": ""})
            elif isinstance(fm, dict):
                tier = normalize_capability_tier(fm.get("capability_tier"), fm.get("intensity"))
                model = fm.get("model", "deepseek_pro")
                chain.append({
                    "worker": fm.get("worker", "claude_code"),
                    "model": model,
                    "variant": fm.get("variant"),
                    "capability_tier": tier,
                    "capability_profile": capability_profile(model, tier, fm.get("intensity")),
                    "reason": fm.get("reason", f"escalation to {fm.get('model', 'unknown')}"),
                    "status": "",
                })

    # If route says opencode_on_failure, ensure opencode fallback exists
    if route.get("escalation_policy") == "opencode_on_failure":
        has_opencode = any(a["worker"] == "opencode" for a in chain)
        if not has_opencode:
            chain.append({
                "worker": "opencode", "model": "opencode_go_glm52",
                "variant": "high", "capability_tier": "high",
                "capability_profile": capability_profile("opencode_go_glm52", "high", "high"),
                "reason": "ClaudeCodeWorker failed; escalate to GLM-5.2 high",
                "status": "",
            })
            chain.append({
                "worker": "opencode", "model": "opencode_go_glm52",
                "variant": "max", "capability_tier": "max",
                "capability_profile": capability_profile("opencode_go_glm52", "max", "max"),
                "reason": "GLM-5.2 high failed; escalate to max",
                "status": "",
            })

    return chain


_RETRYABLE_FAILURES = {"worker_failed", "tests_failed", "patch_failed", "command_timeout", "failed"}
_NON_RETRYABLE_FAILURES = {"forbidden_path", "dangerous_command", "secret_exposure", "approval_rejected", "blocked", "cancelled"}


def _task_requires_diff(task: dict[str, Any]) -> bool:
    goal = str(task.get("user_goal", "")).lower()
    task_type = str(task.get("task_type", "")).lower()
    if task.get("allow_empty_diff") is True:
        return False
    edit_markers = (
        "fix",
        "bug",
        "modify",
        "change",
        "update",
        "edit",
        "add",
        "implement",
        "refactor",
        "修复",
        "修改",
        "更新",
        "实现",
        "新增",
    )
    if any(marker in goal for marker in edit_markers):
        return True
    return task_type in {"simple_bugfix", "routine_coding", "complex_coding", "hard_bugfix", "large_refactor"}


def _is_retryable_failure(result) -> bool:
    """Check if a worker failure is retryable."""
    status = getattr(result, "status", "failed")
    if status in _NON_RETRYABLE_FAILURES or status == "blocked":
        return False
    return status in _RETRYABLE_FAILURES or status == "failed"


def _should_recover_failed_worker_diff(result) -> bool:
    """Allow verification to judge a failed worker run that produced a diff."""
    if getattr(result, "status", "") != "failed":
        return False
    return bool(getattr(result, "changed_files", []))


_OPENCODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "opencode_worker_prompt.md"
_CLAUDE_CODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "claude_code_worker_prompt.md"


def _worker_prompt(task: dict[str, Any], route: dict[str, Any]) -> str:
    worker = str(route.get("selected_worker", "")).lower()
    task_section = (
        f"\n\n## Task Context\n\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        f"Worktree: {task.get('worktree_path', '')}\n"
        f"Risk level: {task.get('risk_level', 'medium')}\n"
        f"Test commands: {json.dumps(task.get('test_commands', []), ensure_ascii=False)}\n"
        f"Build commands: {json.dumps(task.get('build_commands', []), ensure_ascii=False)}\n"
        f"Forbidden paths: {json.dumps(task.get('forbidden_paths', []), ensure_ascii=False)}\n"
        "Do not read run artifacts outside the worktree; this prompt is the authoritative task context.\n"
        "World Core will run the listed verification commands after you return; do not spend many turns on full-suite testing.\n"
        "Return changed_files, summary, test_suggestions, risks, needs_user."
    )
    if worker == "opencode":
        prompt_path = _OPENCODE_WORKER_PROMPT_PATH
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").rstrip() + task_section
    if worker == "claude_code":
        prompt_path = _CLAUDE_CODE_WORKER_PROMPT_PATH
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").rstrip() + task_section
    return (
        "You are a background coding worker. Do not push, merge, or edit forbidden paths.\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        "Return changed_files, summary, test_suggestions, risks."
    )


def _dry_verify(task: dict[str, Any]):
    from .verifier import VerifyResult

    diff_path = str(Path(task["run_dir"]) / "verify" / "diff.patch")
    Path(diff_path).parent.mkdir(parents=True, exist_ok=True)
    Path(diff_path).write_text("", encoding="utf-8")
    return VerifyResult(True, True, [], [], diff_path, True, _now())


def _final_md(task: dict[str, Any], route: dict[str, Any], worker: dict[str, Any], verify_result: dict[str, Any], review: dict[str, Any]) -> str:
    return f"""# Task Result

## Summary

- Task: {task['user_goal']}
- Project: {task['project_id']}
- Worker: {route['selected_worker']}
- Model: {route['selected_model']}
- Status: completed

## Worker

{worker.get('summary', '')}

## Verification

- Tests passed: {verify_result.get('tests_passed')}
- Build passed: {verify_result.get('build_passed')}

## Review

- Mode: {review.get('review_mode', 'unknown')}
- Degraded: {review.get('degraded', False)}
- Degradation reason: {review.get('degradation_reason')}
- Approved: {review.get('approved')}
- Can create PR: {review.get('can_create_pr')}

## Safety

V1 never auto-merges PRs.
"""
