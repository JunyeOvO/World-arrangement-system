from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .db import TaskDB
from .pr import PublishResult, create_pr_or_patch


@dataclass
class TaskPublishOutcome:
    publish_result: PublishResult
    status: str
    event_type: str
    payload: dict[str, Any]
    pr_created: bool = False


class TaskPublishRunner:
    """Publishes a verified task as a PR or patch artifact."""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        db: TaskDB,
        publish_func: Callable[..., PublishResult] = create_pr_or_patch,
        now: Callable[[], str],
    ) -> None:
        self.artifacts = artifacts
        self.db = db
        self.publish_func = publish_func
        self.now = now

    def run(
        self,
        *,
        task_id: str,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree_path: Path,
        branch: str,
    ) -> TaskPublishOutcome:
        publish_result = self.publish_func(
            worktree_path,
            branch,
            project.get("pr_base_branch", project.get("default_branch", "main")),
            f"[ai-orchestrator] {task['user_goal'][:60]}",
            Path(task["run_dir"]) / "final.md",
            Path(task["run_dir"]) / "verify" / "diff.patch",
            allow_remote_push=project.get("allow_remote_push", False),
        )
        self.artifacts.write_json(task_id, "publish.json", publish_result.__dict__)
        if publish_result.status == "PR_CREATED":
            self.db.update_task(task_id, pr_url=publish_result.pr_url, updated_at=self.now())
            return TaskPublishOutcome(
                publish_result=publish_result,
                status="PR_CREATED",
                event_type="pr_created",
                payload=publish_result.__dict__,
                pr_created=True,
            )
        if publish_result.status == "COMPLETED_WITH_PATCH":
            return TaskPublishOutcome(
                publish_result=publish_result,
                status="COMPLETED_WITH_PATCH",
                event_type="completed_with_patch",
                payload=publish_result.__dict__,
            )
        if publish_result.status == "COMPLETED_NO_CHANGES":
            return TaskPublishOutcome(
                publish_result=publish_result,
                status="COMPLETED_NO_CHANGES",
                event_type="completed_no_changes",
                payload=publish_result.__dict__,
            )
        return TaskPublishOutcome(
            publish_result=publish_result,
            status="DONE",
            event_type="completed_without_publish",
            payload=publish_result.__dict__,
        )
