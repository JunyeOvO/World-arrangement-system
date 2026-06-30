from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB
from orchestrator.pr import PublishResult
from orchestrator.task_publish import TaskPublishRunner


def test_task_publish_runner_maps_patch_result_and_writes_artifact(tmp_path):
    db, run_dir = _task_db(tmp_path, "t_patch")

    def fake_publish(worktree, branch, base_branch, title, body_path, diff_path, allow_remote_push=False):
        assert branch == "world/t_patch"
        assert base_branch == "main"
        assert "fix bug" in title
        assert body_path == run_dir / "final.md"
        assert diff_path == run_dir / "verify" / "diff.patch"
        assert allow_remote_push is False
        return PublishResult("COMPLETED_WITH_PATCH", None, str(diff_path), "patch ready")

    runner = TaskPublishRunner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        db=db,
        publish_func=fake_publish,
        now=lambda: "2026-06-30T01:00:02Z",
    )

    outcome = runner.run(
        task_id="t_patch",
        task={"task_id": "t_patch", "run_dir": str(run_dir), "user_goal": "fix bug"},
        project={"default_branch": "main", "allow_remote_push": False},
        worktree_path=tmp_path / "worktree",
        branch="world/t_patch",
    )

    assert outcome.status == "COMPLETED_WITH_PATCH"
    assert outcome.event_type == "completed_with_patch"
    assert not outcome.pr_created
    assert json.loads((run_dir / "publish.json").read_text(encoding="utf-8"))["message"] == "patch ready"


def test_task_publish_runner_updates_pr_url_for_created_pr(tmp_path):
    db, run_dir = _task_db(tmp_path, "t_pr")
    runner = TaskPublishRunner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        db=db,
        publish_func=lambda *args, **kwargs: PublishResult(
            "PR_CREATED",
            "https://github.com/example/repo/pull/1",
            None,
            "created",
        ),
        now=lambda: "2026-06-30T01:00:02Z",
    )

    outcome = runner.run(
        task_id="t_pr",
        task={"task_id": "t_pr", "run_dir": str(run_dir), "user_goal": "fix bug"},
        project={"default_branch": "main", "allow_remote_push": True},
        worktree_path=tmp_path / "worktree",
        branch="world/t_pr",
    )

    assert outcome.status == "PR_CREATED"
    assert outcome.event_type == "pr_created"
    assert outcome.pr_created
    assert db.get_task("t_pr")["pr_url"] == "https://github.com/example/repo/pull/1"


def _task_db(tmp_path: Path, task_id: str) -> tuple[TaskDB, Path]:
    run_dir = tmp_path / "runs" / task_id
    (run_dir / "verify").mkdir(parents=True)
    (run_dir / "final.md").write_text("# Done\n", encoding="utf-8")
    (run_dir / "verify" / "diff.patch").write_text("diff --git\n", encoding="utf-8")
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": task_id,
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "fix bug",
            "status": "PLANNED",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(run_dir),
        }
    )
    return db, run_dir
