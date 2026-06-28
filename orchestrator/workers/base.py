from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkerResult:
    status: str
    summary: str
    changed_files: list[str] = field(default_factory=list)
    test_suggestions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    needs_orchestrator_action: bool = False
    stdout_path: str | None = None
    stderr_path: str | None = None
    # vNext fields (World Adaptive Parallelism)
    patch_file: str | None = None
    tests_run: list[dict] = field(default_factory=list)
    rollback_notes: str | None = None


class Worker:
    name = "base"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        raise NotImplementedError

