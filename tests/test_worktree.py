from pathlib import Path

import pytest

from orchestrator.worktree import WorktreeError, cleanup_worktree, prepare_worktree


def test_dry_run_worktree(tmp_path: Path):
    info = prepare_worktree("/not/a/repo", "main", "task1", tmp_path, dry_run=True)
    assert Path(info.path).exists()
    cleanup_worktree("/not/a/repo", info.path, dry_run=True)
    assert not Path(info.path).exists()


def test_prepare_worktree_rejects_unsafe_task_id(tmp_path: Path):
    with pytest.raises(WorktreeError):
        prepare_worktree("/not/a/repo", "main", "../escape", tmp_path, dry_run=True)


def test_dry_run_cleanup_refuses_repo_root(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(WorktreeError):
        cleanup_worktree(str(repo), str(repo), dry_run=True)


def test_dry_run_cleanup_refuses_path_outside_worktrees(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "not-worktrees" / "task1"
    outside.mkdir(parents=True)

    with pytest.raises(WorktreeError):
        cleanup_worktree(str(repo), str(outside), dry_run=True)

    assert outside.exists()
