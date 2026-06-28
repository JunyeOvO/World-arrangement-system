from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PublishResult:
    status: str
    pr_url: str | None
    patch_path: str | None
    message: str


def create_pr_or_patch(
    worktree: Path,
    branch: str,
    base_branch: str,
    title: str,
    body_path: Path,
    diff_path: Path,
    allow_remote_push: bool = False,
) -> PublishResult:
    fallback_status = "COMPLETED_WITH_PATCH" if _has_diff(diff_path) else "COMPLETED_NO_CHANGES"
    if not allow_remote_push:
        return PublishResult(fallback_status, None, str(diff_path), "remote push disabled")
    if not shutil.which("gh"):
        return PublishResult(fallback_status, None, str(diff_path), "gh CLI not found")
    push = subprocess.run(
        ["git", "-C", str(worktree), "push", "origin", f"HEAD:{branch}"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=300,
        check=False,
    )
    if push.returncode != 0:
        return PublishResult(fallback_status, None, str(diff_path), push.stderr.strip())
    pr = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--base",
            base_branch,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ],
        cwd=worktree,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=300,
        check=False,
    )
    if pr.returncode != 0:
        return PublishResult(fallback_status, None, str(diff_path), pr.stderr.strip())
    return PublishResult("PR_CREATED", pr.stdout.strip(), None, "PR created")


def _has_diff(diff_path: Path) -> bool:
    try:
        return bool(diff_path.read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return False
