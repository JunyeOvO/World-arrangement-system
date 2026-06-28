from pathlib import Path

from orchestrator.worktree import cleanup_worktree, prepare_worktree


def test_dry_run_worktree(tmp_path: Path):
    info = prepare_worktree("/not/a/repo", "main", "task1", tmp_path, dry_run=True)
    assert Path(info.path).exists()
    cleanup_worktree("/not/a/repo", info.path, dry_run=True)
    assert not Path(info.path).exists()

