from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .artifacts import ArtifactStore
from .codex_usage import build_codex_usage_event
from .db import TaskDB


class CodexUsageRecorder:
    """Records estimated or actual Codex-side usage for World orchestration phases."""

    def __init__(
        self,
        *,
        db: TaskDB,
        artifacts: ArtifactStore,
        write_token_ledger: Callable[[str], None],
    ) -> None:
        self.db = db
        self.artifacts = artifacts
        self.write_token_ledger = write_token_ledger

    def record_planning_dispatch(
        self,
        *,
        task_id: str,
        project_id: str,
        repo_path: str,
        user_goal: str,
        risk_level: str,
        auto_execute: bool,
        auto_pr: bool,
        dry_run: bool,
        force_worker: str | None,
        force_model: str | None,
        force_variant: str | None,
        has_images: bool,
        protocol: dict[str, Any],
        project_memory: dict[str, Any],
        run_dir: str,
    ) -> None:
        self.record_event(
            build_codex_usage_event(
                task_id=task_id,
                phase="planning_dispatch",
                input_payload={
                    "project_id": project_id,
                    "repo_path": repo_path,
                    "user_goal": user_goal,
                    "risk_level": risk_level,
                    "auto_execute": auto_execute,
                    "auto_pr": auto_pr,
                    "dry_run": dry_run,
                    "force_worker": force_worker,
                    "force_model": force_model,
                    "force_variant": force_variant,
                    "has_images": has_images,
                    "task_mode": protocol["task_mode"],
                    "expected_diff": protocol["expected_diff"],
                    "verification_policy": protocol["verification_policy"],
                    "read_budget_profile": protocol["read_budget_profile"],
                    "read_budget": protocol["read_budget"],
                    "project_memory_stats": project_memory.get("memory", {}).get("stats", {}),
                },
                output_payload={
                    "task_id": task_id,
                    "status": "QUEUED",
                    "run_dir": run_dir,
                },
                metadata={
                    "measured": False,
                    "scope": "codex_main_thread_task_spec_and_dispatch",
                    "goal": "estimate Codex quota consumed before World worker execution",
                },
            )
        )

    def record_review_usage(self, task_id: str, review_inputs: dict[str, Any], review: dict[str, Any]) -> None:
        self.record_event(
            build_codex_usage_event(
                task_id=task_id,
                phase="world_review",
                input_payload={
                    "prompt_prefix": (
                        "Review this orchestrator task. Output only JSON with keys "
                        "approved,risk_level,blocking_issues,non_blocking_issues,required_changes,"
                        "final_recommendation,can_create_pr."
                    ),
                    "inputs": review_inputs,
                },
                output_payload=review,
                actual_codex_used=review.get("review_mode") == "codex" and not bool(review.get("degraded")),
                metadata={
                    "measured": False,
                    "review_mode": review.get("review_mode"),
                    "degraded": bool(review.get("degraded")),
                    "available": bool(review.get("available")),
                    "approved": bool(review.get("approved")),
                    "scope": "codex_review_gate",
                },
            )
        )

    def record_event(self, event: dict[str, Any]) -> None:
        self.db.record_codex_usage_event(event)
        phase = str(event.get("phase") or "unknown")
        self.artifacts.append_jsonl(event["task_id"], "codex_usage/events.jsonl", event)
        self.artifacts.write_json(event["task_id"], f"codex_usage/{phase}.json", event)
        self.db.append_event(
            event["task_id"],
            "codex_usage_recorded",
            None,
            None,
            {
                "phase": phase,
                "input_tokens": event.get("input_tokens", 0),
                "output_tokens": event.get("output_tokens", 0),
                "total_tokens": event.get("total_tokens", 0),
                "actual_codex_used": bool(event.get("actual_codex_used")),
                "estimation_method": event.get("estimation_method"),
            },
        )
        self.write_token_ledger(str(event["task_id"]))
