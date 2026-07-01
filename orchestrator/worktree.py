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
    task_id = _safe_path_segment(task_id, "task_id")
    branch = f"ai/{task_id}"
    worktrees_root = (root / "worktrees").resolve()
    target = (worktrees_root / task_id).resolve()
    target.relative_to(worktrees_root)
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
        target = Path(path).resolve()
        repo_path = Path(repo).resolve()
        if target == repo_path:
            raise WorktreeError("refusing to cleanup repository root")
        if target.parent.name != "worktrees":
            raise WorktreeError("refusing to cleanup path outside worktrees directory")
        shutil.rmtree(target, ignore_errors=True)
        return
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", path], timeout=60, check=False)


def _safe_path_segment(value: str, field: str) -> str:
    text = str(value or "")
    if not text or text in {".", ".."}:
        raise WorktreeError(f"invalid {field}: empty or relative segment")
    if "/" in text or "\\" in text:
        raise WorktreeError(f"invalid {field}: path separators are not allowed")
    if Path(text).name != text:
        raise WorktreeError(f"invalid {field}: must be a single path segment")
    return text
