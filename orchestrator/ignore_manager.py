from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WORLD_IGNORE_MARKER = "# World System local runtime"
WORLD_IGNORE_BLOCK = """# World System local runtime
.world/
.world-runs/
.world-cache/
.world-lock.json
world.result.json
"""


@dataclass(frozen=True)
class IgnoreResult:
    changed: bool
    exclude_path: str
    reason: str


def ensure_world_ignored(repo_path: str | Path) -> IgnoreResult:
    """Ensure repo-local World runtime paths are ignored via .git/info/exclude.

    This deliberately avoids editing .gitignore. It is used only for the
    ignored_write fallback policy.
    """
    repo = Path(repo_path).resolve()
    exclude_path = repo / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        raise RuntimeError(f"not a git repository or exclude unavailable: {repo}")

    text = exclude_path.read_text(encoding="utf-8")
    if WORLD_IGNORE_MARKER in text:
        return IgnoreResult(False, str(exclude_path), "World ignore block already present")

    prefix = "" if text.endswith("\n") else "\n"
    exclude_path.write_text(text + prefix + "\n" + WORLD_IGNORE_BLOCK, encoding="utf-8")
    return IgnoreResult(True, str(exclude_path), "World ignore block appended")


def remove_world_ignore_block(repo_path: str | Path) -> IgnoreResult:
    """Remove the World ignore block from .git/info/exclude if present."""
    repo = Path(repo_path).resolve()
    exclude_path = repo / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        raise RuntimeError(f"not a git repository or exclude unavailable: {repo}")

    text = exclude_path.read_text(encoding="utf-8")
    if WORLD_IGNORE_MARKER not in text:
        return IgnoreResult(False, str(exclude_path), "World ignore block absent")

    updated = text.replace("\n" + WORLD_IGNORE_BLOCK, "\n").replace(WORLD_IGNORE_BLOCK, "")
    exclude_path.write_text(updated, encoding="utf-8")
    return IgnoreResult(True, str(exclude_path), "World ignore block removed")
