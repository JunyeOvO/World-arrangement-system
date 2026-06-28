from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path


def matches_any_glob(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any glob pattern in the list."""
    return any(fnmatch(rel_path, pat) for pat in patterns)


def validate_file_ownership(
    changed_files: list[str], owned_paths: list[str], forbidden_paths: list[str]
) -> list[str]:
    """Check changed files against owned and forbidden path globs."""
    violations: list[str] = []
    for path in changed_files:
        if forbidden_paths and matches_any_glob(path, forbidden_paths):
            violations.append(f"forbidden path modified: {path}")
        elif owned_paths and not matches_any_glob(path, owned_paths):
            violations.append(f"file outside owned_paths: {path}")
    return violations


def detect_changed_files(worktree: Path) -> list[str]:
    """Return changed file paths relative to the worktree root."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def export_patch(worktree: Path, patch_path: Path) -> bool:
    """Export git diff --binary from the worktree to a patch file."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--binary", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.returncode != 0:
            return False
        diff_text = proc.stdout or ""
        if not diff_text.strip():
            return False
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(diff_text, encoding="utf-8")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
