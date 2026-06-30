from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .command_utils import command_available
from .constants import DEFAULT_CLAUDE_CMD, DEFAULT_OPENCODE_CMD
from .runtime_store import RuntimeStore
from .router import plan_route


class WorldRuntimeService:
    """Owns external World runtime bootstrap, planning, and health checks."""

    def __init__(
        self,
        *,
        profile_project: Callable[[str, bool], dict[str, Any]],
        detect_project: Callable[..., dict[str, Any]],
        model_metrics_summary: Callable[[], list[dict[str, Any]]],
        new_run_id: Callable[[], str],
    ) -> None:
        self.profile_project = profile_project
        self.detect_project = detect_project
        self.model_metrics_summary = model_metrics_summary
        self.new_run_id = new_run_id

    def bootstrap(
        self,
        repo_path: str,
        user_prompt: str = "本项目开发使用 World 系统",
        preferred_write_policy: str = "zero_write",
    ) -> dict[str, Any]:
        """Bootstrap World for a repo without writing World core files into it."""
        store = RuntimeStore(repo_path, preferred_write_policy)  # type: ignore[arg-type]
        profile = self.profile_project(repo_path, False)
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

    def profile(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        return self.profile_project(repo_path, force)

    def create_plan(
        self,
        repo_path: str,
        user_goal: str,
        risk_level: str = "medium",
        preferred_write_policy: str = "zero_write",
    ) -> dict[str, Any]:
        """Create a WorldPlan and write it to the external RuntimeStore."""
        store = RuntimeStore(repo_path, preferred_write_policy)  # type: ignore[arg-type]
        run_id = self.new_run_id().replace("t_", "world_", 1)
        profile = self.profile_project(repo_path, False)
        project = {
            "project_id": store.project_id,
            "repo": str(Path(repo_path).expanduser().resolve()),
            "stack": profile.get("profile", {}).get("detected_types", []) if isinstance(profile, dict) else [],
            "test_commands": profile.get("profile", {}).get("test_commands", []) if isinstance(profile, dict) else [],
            "build_commands": profile.get("profile", {}).get("build_commands", []) if isinstance(profile, dict) else [],
            "default_worker": "claude_code",
            "default_model": "deepseek_pro",
        }
        route = self.build_plan_route(user_goal, risk_level, project)
        plan = {
            "run_id": run_id,
            "project_id": store.project_id,
            "repo_path": str(Path(repo_path).expanduser().resolve()),
            "user_goal": user_goal,
            "risk_level": risk_level,
            "write_policy": preferred_write_policy,
            "runtime_backend": store.backend,
            "route": route,
            "safe_parallelism": safe_parallelism_from_profile(profile),
            "worker_required": True,
            "final_review": "World Review",
        }
        plan_path = store.write_plan(run_id, plan)
        return {"plan": plan, "plan_path": str(plan_path), "runtime_store": str(store.project_dir)}

    def doctor(self, repo_path: str | None = None) -> dict[str, Any]:
        """World health check for RuntimeStore and worker command availability."""
        checks: list[dict[str, Any]] = []
        for label, command in {
            "git": "git",
            "claude": os.environ.get("AI_CLAUDE_CMD", DEFAULT_CLAUDE_CMD),
                "opencode": os.environ.get("AI_OPENCODE_CMD", DEFAULT_OPENCODE_CMD),
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
            except Exception as exc:  # pragma: no cover - defensive health output
                checks.append({"name": "RuntimeStore available", "ok": False, "detail": str(exc)})
        status = "healthy" if all(c["ok"] for c in checks if c["name"] in {"git available", "RuntimeStore available"}) else "degraded"
        return {"status": status, "checks": checks, "runtime": runtime}

    def build_plan_route(self, user_goal: str, risk_level: str, project: dict[str, Any]) -> dict[str, Any]:
        return plan_route(
            {"user_goal": user_goal, "risk_level": risk_level},
            project,
            history=self.model_metrics_summary(),
        ).to_dict()


def safe_parallelism_from_profile(profile: dict[str, Any]) -> int:
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
