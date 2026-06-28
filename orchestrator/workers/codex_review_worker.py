from __future__ import annotations

from pathlib import Path

from .base import Worker, WorkerResult


class CodexReviewWorker(Worker):
    name = "codex_reviewer"

    def run(self, prompt: str, worktree: Path, route: dict, task: dict, dry_run: bool = False) -> WorkerResult:
        return WorkerResult(
            "success",
            "Codex review is handled by orchestrator.reviewer, not as an editing worker",
            [],
            [],
            [],
            False,
        )

