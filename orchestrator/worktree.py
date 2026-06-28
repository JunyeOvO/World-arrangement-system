from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    pass


@dataclass
class WorktreeInfo:
    repo: str
    branch: str
    path: str
    dry_run: bool = False


def prepare_worktree(repo: str, base_branch: str, task_id: str, root: Path, dry_run: bool = False) -> WorktreeInfo:
    branch = f"ai/{task_id}"
    target = root / "worktrees" / task_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        target.mkdir(parents=True, exist_ok=True)
        return WorktreeInfo(repo=repo, branch=branch, path=str(target), dry_run=True)
    if not (Path(repo) / ".git").exists():
        raise WorktreeError(f"not a git repository: {repo}")
    if target.exists():
        shutil.rmtree(target)
    cmd = ["git", "-C", repo, "worktree", "add", "-b", branch, str(target), base_branch]
    proc = subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise WorktreeError(proc.stderr.strip() or proc.stdout.strip())
    return WorktreeInfo(repo=repo, branch=branch, path=str(target), dry_run=False)


def cleanup_worktree(repo: str, path: str, dry_run: bool = False) -> None:
    if dry_run:
        shutil.rmtree(path, ignore_errors=True)
        return
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", path], timeout=60, check=False)
