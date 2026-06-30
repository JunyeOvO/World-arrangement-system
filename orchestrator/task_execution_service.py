from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .db import TaskDB
from .task_protocol import apply_read_budget_to_route


class TaskExecutionService:
    """Coordinates the execution pipeline after a task has been submitted."""

    def __init__(
        self,
        *,
        db: TaskDB,
        artifacts: ArtifactStore,
        execution_gate,
        route_planner,
        preparation,
        attempt_runner,
        completion_pipeline,
        set_status: Callable[[str, str, str, dict[str, Any]], None],
        record_policy_learning: Callable[..., None],
        now: Callable[[], str],
    ) -> None:
        self.db = db
        self.artifacts = artifacts
        self.execution_gate = execution_gate
        self.route_planner = route_planner
        self.preparation = preparation
        self.attempt_runner = attempt_runner
        self.completion_pipeline = completion_pipeline
        self.set_status = set_status
        self.record_policy_learning = record_policy_learning
        self.now = now

    def execute(self, task: dict[str, Any], project: dict[str, Any], dry_run: bool = False) -> None:
        task_id = task["task_id"]
        gate = self.execution_gate.run(task, project)
        for transition in gate.transitions:
            self.set_status(task_id, transition.status, transition.event_type, transition.payload)
        if not gate.continue_execution:
            if gate.policy_incident:
                self.record_policy_learning(task, project, success=False, incident=True)
            return

        route = self.route_planner.route_for_task(task, project)
        route = apply_read_budget_to_route(route, task)
        self.artifacts.write_json(task_id, "route.json", route)
        self.db.update_task(
            task_id,
            route_worker=route["selected_worker"],
            route_model=route["selected_model"],
            route_variant=route.get("variant") or "",
            updated_at=self.now(),
        )
        self.set_status(task_id, "ROUTED", "routed", route)

        preparation = self.preparation.prepare(
            task_id=task_id,
            task=task,
            project=project,
            route=route,
            dry_run=dry_run,
        )
        wt = preparation.worktree

        attempt_run = self.attempt_runner.run(
            task_id=task_id,
            task=task,
            route=route,
            worktree_path=Path(wt.path),
            dry_run=dry_run,
        )
        if attempt_run.terminal_status:
            self.set_status(task_id, attempt_run.terminal_status, attempt_run.terminal_event or "", attempt_run.terminal_payload)
        if not attempt_run.completed:
            if attempt_run.policy_signal:
                signal = attempt_run.policy_signal
                self.record_policy_learning(
                    task,
                    project,
                    success=signal.success,
                    worker=signal.worker,
                    model=signal.model,
                    rollback=signal.rollback,
                    incident=signal.incident,
                )
            return

        self.completion_pipeline.run(
            task_id=task_id,
            task=task,
            project=project,
            route=route,
            worker_result=attempt_run.final_result,
            last_attempt=attempt_run.last_attempt,
            worktree_path=Path(wt.path),
            branch=wt.branch,
            dry_run=dry_run,
        )
