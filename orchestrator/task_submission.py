from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project_memory import ensure_project_memory
from .task_protocol import normalize_task_protocol


@dataclass
class TaskSubmission:
    task: dict[str, Any]
    protocol: dict[str, Any]
    project_memory: dict[str, Any]


class TaskSubmissionBuilder:
    """Builds normalized task payloads for scheduler submission."""

    def build(
        self,
        *,
        task_id: str,
        run_dir: Path,
        now: str,
        project_id: str,
        project: dict[str, Any],
        user_goal: str,
        risk_level: str,
        auto_execute: bool,
        auto_pr: bool,
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
    ) -> TaskSubmission:
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
        return TaskSubmission(task=task, protocol=protocol, project_memory=memory_payload)
