from __future__ import annotations

from pathlib import Path

from .base import Worker, WorkerResult


class MimoWorker(Worker):
    name = "mimo"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        return WorkerResult(
            "partial",
            "MiMo multimodal worker is scaffolded; provide API integration before real multimodal execution",
            [],
            [],
            ["mimo API integration not configured"],
            True,
        )

