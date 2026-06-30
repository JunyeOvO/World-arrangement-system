from __future__ import annotations

import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.codex_usage_recording import CodexUsageRecorder
from orchestrator.db import TaskDB


def _recorder(tmp_path: Path) -> tuple[CodexUsageRecorder, TaskDB, ArtifactStore, list[str]]:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    artifacts = ArtifactStore(tmp_path / "runs")
    ledger_calls: list[str] = []
    return (
        CodexUsageRecorder(
            db=db,
            artifacts=artifacts,
            write_token_ledger=ledger_calls.append,
        ),
        db,
        artifacts,
        ledger_calls,
    )


def test_record_planning_dispatch_writes_usage_event_artifact_and_audit(tmp_path: Path) -> None:
    recorder, db, artifacts, ledger_calls = _recorder(tmp_path)
    artifacts.run_dir("t_codex")

    recorder.record_planning_dispatch(
        task_id="t_codex",
        project_id="generic",
        repo_path=str(tmp_path / "repo"),
        user_goal="fix bug",
        risk_level="medium",
        auto_execute=True,
        auto_pr=False,
        dry_run=False,
        force_worker=None,
        force_model=None,
        force_variant=None,
        has_images=False,
        protocol={
            "task_mode": "patch",
            "expected_diff": True,
            "verification_policy": "full",
            "read_budget_profile": "quick_triage",
            "read_budget": {"max_files": 6},
        },
        project_memory={"memory": {"stats": {"hit_count": 2, "miss_count": 1}}},
        run_dir=str(artifacts.run_dir("t_codex")),
    )

    rows = db.list_codex_usage_events(task_id="t_codex")
    audit_events = db.list_events("t_codex")
    artifact = json.loads((artifacts.run_dir("t_codex") / "codex_usage" / "planning_dispatch.json").read_text(encoding="utf-8"))

    assert len(rows) == 1
    assert rows[0]["phase"] == "planning_dispatch"
    assert rows[0]["metadata"]["scope"] == "codex_main_thread_task_spec_and_dispatch"
    assert artifact["total_tokens"] == rows[0]["total_tokens"]
    assert audit_events[-1]["event_type"] == "codex_usage_recorded"
    assert ledger_calls == ["t_codex"]


def test_record_review_usage_marks_actual_codex_review(tmp_path: Path) -> None:
    recorder, db, artifacts, ledger_calls = _recorder(tmp_path)
    artifacts.run_dir("t_review")

    recorder.record_review_usage(
        "t_review",
        {"tests_passed": True, "changed_files": ["a.py"]},
        {"approved": True, "review_mode": "codex", "degraded": False, "available": True},
    )

    rows = db.list_codex_usage_events(task_id="t_review")
    artifact = json.loads((artifacts.run_dir("t_review") / "codex_usage" / "world_review.json").read_text(encoding="utf-8"))

    assert len(rows) == 1
    assert rows[0]["phase"] == "world_review"
    assert rows[0]["actual_codex_used"] == 1
    assert rows[0]["metadata"]["scope"] == "codex_review_gate"
    assert artifact["actual_codex_used"] is True
    assert ledger_calls == ["t_review"]


def test_record_review_usage_treats_degraded_review_as_estimated(tmp_path: Path) -> None:
    recorder, db, artifacts, _ = _recorder(tmp_path)
    artifacts.run_dir("t_degraded_review")

    recorder.record_review_usage(
        "t_degraded_review",
        {"tests_passed": True},
        {"approved": False, "review_mode": "local_fallback", "degraded": True, "available": False},
    )

    rows = db.list_codex_usage_events(task_id="t_degraded_review")
    assert rows[0]["phase"] == "world_review"
    assert rows[0]["actual_codex_used"] == 0
    assert rows[0]["metadata"]["degraded"] is True
