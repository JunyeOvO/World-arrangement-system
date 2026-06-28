from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import code_root

AGENTS_MD_NAME = "AGENTS.md"


@dataclass(frozen=True)
class InjectResult:
    injected: bool
    path: str
    reason: str


def _template_path() -> Path:
    return code_root() / "config" / "AGENTS.md.template"


def inject_agents_md(worktree: Path, force: bool = False) -> InjectResult:
    """Inject AGENTS.md into a worktree for OpenCodeWorker.

    Never overwrites an existing AGENTS.md unless ``force`` is True. When the
    file already exists, skip injection and return a warning reason so the
    caller can record it in the task artifacts.
    """
    target = Path(worktree) / AGENTS_MD_NAME
    template = _template_path()

    if target.exists() and not force:
        return InjectResult(
            injected=False,
            path=str(target),
            reason="AGENTS.md already exists in worktree; skipped to avoid overwriting user file",
        )

    if not template.exists():
        return InjectResult(
            injected=False,
            path=str(target),
            reason=f"AGENTS.md template missing: {template}",
        )

    worktree.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, target)
    return InjectResult(
        injected=True,
        path=str(target),
        reason="injected from AGENTS.md.template",
    )