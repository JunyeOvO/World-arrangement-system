"""Worktree and pre-attempt preparation for task execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .agents_md import inject_agents_md
from .artifacts import ArtifactStore
from .multimodal import load_image_inputs
from .project_memory import ensure_project_memory
from .workers.mimo_vision_adapter import MimoVisionAdapter
from .worktree import WorktreeInfo, prepare_worktree


@dataclass
class TaskPreparationResult:
    worktree: WorktreeInfo


class TaskPreparationService:
    """Prepares worktree, optional vision context, and route-specific files."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        set_status: Callable[[str, str, str, dict[str, Any]], None],
        worktree_preparer: Callable[..., WorktreeInfo] = prepare_worktree,
        agents_injector: Callable[[Path], Any] = inject_agents_md,
        vision_adapter_factory: Callable[[], MimoVisionAdapter] = MimoVisionAdapter,
        project_memory_refresher: Callable[..., dict[str, Any]] = ensure_project_memory,
    ) -> None:
        self.artifacts = artifacts
        self.set_status = set_status
        self.worktree_preparer = worktree_preparer
        self.agents_injector = agents_injector
        self.vision_adapter_factory = vision_adapter_factory
        self.project_memory_refresher = project_memory_refresher

    def prepare(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        project: dict[str, Any],
        route: dict[str, Any],
        dry_run: bool = False,
    ) -> TaskPreparationResult:
        worktree = self.worktree_preparer(
            project["repo"],
            project.get("default_branch", "main"),
            task_id,
            Path(task["run_dir"]),
            dry_run=dry_run,
        )
        self.artifacts.write_json(task_id, "worktree.json", worktree.__dict__)
        task["worktree_path"] = worktree.path
        self.set_status(task_id, "WORKTREE_READY", "worktree_ready", worktree.__dict__)

        task["project_memory"] = self.project_memory_refresher(
            str(task.get("project_id") or project.get("project_id") or ""),
            project,
            source_path=worktree.path,
            source_kind="worktree",
            source_ref=task_id,
        )
        self.artifacts.write_json(task_id, "task.json", task)
        self.set_status(task_id, "WORKTREE_READY", "project_memory_refreshed", {
            "source_kind": "worktree",
            "source_ref": task_id,
            "path": task["project_memory"].get("path"),
        })

        if task.get("image_paths") or task.get("image_base64"):
            observation = self._run_mimo_vision(task, dry_run=dry_run)
            task["vision_observation"] = observation
            task["vision_observation_path"] = str(Path(task["run_dir"]) / "multimodal" / "vision_observation.json")
            self.artifacts.write_json(task_id, "task.json", task)
            self.set_status(task_id, "WORKTREE_READY", "vision_observation_ready", {
                "path": task["vision_observation_path"],
                "degraded": observation.get("degraded", False),
                "confidence": observation.get("confidence"),
            })

        if route.get("selected_worker") == "opencode":
            agents_inject = self.agents_injector(Path(worktree.path))
            self.artifacts.write_json(task_id, "agents_md.json", agents_inject.__dict__)
            if not agents_inject.injected:
                self.set_status(task_id, "WORKTREE_READY", "agents_md_skipped", agents_inject.__dict__)

        return TaskPreparationResult(worktree=worktree)

    def _run_mimo_vision(self, task: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        images = load_image_inputs(task.get("image_paths"), task.get("image_base64"))
        observation = self.vision_adapter_factory().analyze(
            task_id=task["task_id"],
            prompt=task["user_goal"],
            images=images,
            output_path=Path(task["run_dir"]) / "multimodal" / "vision_observation.json",
            model_key="mimo_v25",
            dry_run=dry_run,
        )
        return observation.to_dict()
