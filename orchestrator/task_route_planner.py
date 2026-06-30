"""Task route planning facade for scheduler execution."""

from __future__ import annotations

from typing import Any, Callable

from .artifacts import ArtifactStore
from .router import plan_route
from .task_protocol import apply_read_budget_to_route
from .task_routing import (
    apply_route_override,
    world_enabled,
    world_write_policy,
)


class TaskRoutePlanner:
    """Builds canonical execution routes and persists World plan references."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        model_metrics_summary: Callable[[], dict[str, Any]],
        world_plan_factory: Callable[[str, str, str, str], dict[str, Any]],
    ) -> None:
        self.artifacts = artifacts
        self.model_metrics_summary = model_metrics_summary
        self.world_plan_factory = world_plan_factory

    def route_for_task(self, task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        """Return the canonical route for a task.

        World-enabled projects must route through WorldPlan first so submit-task,
        world-create-plan, and MCP entrypoints share the same decision source.
        """
        if world_enabled(project):
            return self._route_world_task(task, project)
        route = plan_route(task, project, history=self.model_metrics_summary()).to_dict()
        return apply_route_override(route, task)

    def _route_world_task(self, task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        plan_result = self.world_plan_factory(
            project["repo"],
            task["user_goal"],
            task.get("risk_level", "medium"),
            world_write_policy(project),
        )
        route = apply_read_budget_to_route(
            apply_route_override(dict(plan_result["plan"]["route"]), task),
            task,
        )
        plan = dict(plan_result["plan"])
        plan["route"] = route
        plan["task_mode"] = task.get("task_mode")
        plan["expected_diff"] = task.get("expected_diff")
        plan["verification_policy"] = task.get("verification_policy")
        plan["read_budget_profile"] = task.get("read_budget_profile")
        plan["read_budget"] = task.get("read_budget")
        task_id = task["task_id"]
        self.artifacts.write_json(task_id, "world_plan.json", plan)
        self.artifacts.write_json(
            task_id,
            "world_plan_ref.json",
            {
                "plan_path": plan_result["plan_path"],
                "runtime_store": plan_result["runtime_store"],
            },
        )
        return route
