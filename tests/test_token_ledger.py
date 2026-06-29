from __future__ import annotations

import json

from orchestrator.db import TaskDB
from orchestrator.token_ledger import build_task_token_ledger, write_task_token_ledger


def test_task_token_ledger_combines_codex_worker_memory_and_cost(tmp_path):
    db = TaskDB(tmp_path / "world.db")
    db.create_task({
        "task_id": "task_1",
        "project_id": "project_1",
        "repo_path": str(tmp_path),
        "user_goal": "fix selected area contract",
        "status": "COMPLETED_WITH_PATCH",
        "created_at": "2026-06-29T01:00:00Z",
        "updated_at": "2026-06-29T01:01:00Z",
        "run_dir": str(tmp_path / "run"),
    })
    db.record_codex_usage_event({
        "task_id": "task_1",
        "phase": "planning_dispatch",
        "model": "codex",
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
        "actual_codex_used": False,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-29T01:00:01Z",
        "metadata": {"scope": "dispatch"},
    })
    db.record_codex_usage_event({
        "task_id": "task_1",
        "phase": "world_review",
        "model": "codex",
        "input_tokens": 2000,
        "output_tokens": 500,
        "total_tokens": 2500,
        "actual_codex_used": True,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-29T01:00:02Z",
        "metadata": {"scope": "review"},
    })
    db.upsert_task_metrics({
        "task_id": "task_1",
        "attempt_no": 1,
        "worker": "opencode",
        "model": "opencode_go_glm52",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 0.5,
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "num_turns": 2,
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 500_000,
        "memory_hit_count": 7,
        "memory_miss_count": 2,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-29T01:01:00Z",
    })

    ledger = build_task_token_ledger(db, "task_1")

    assert ledger["codex"]["total_tokens"] == 4000
    assert ledger["codex"]["actual_total_tokens"] == 2500
    assert ledger["worker"]["total_tokens"] == 1_600_000
    assert ledger["worker"]["calculated_cost_usd"] == 1.97
    assert ledger["worker"]["adapter_reported_cost_usd"] == 0.5
    assert ledger["worker"]["memory_hit_count"] == 7
    assert ledger["worker"]["memory_miss_count"] == 2
    assert ledger["combined"]["total_tokens"] == 1_604_000
    assert ledger["quota_evidence"]["codex_event_count"] == 2
    assert ledger["quota_evidence"]["actual_codex_event_count"] == 1
    assert ledger["counterfactual"]["status"] == "not_measured"


def test_write_task_token_ledger(tmp_path):
    db = TaskDB(tmp_path / "world.db")
    db.create_task({
        "task_id": "task_2",
        "project_id": "project_1",
        "repo_path": str(tmp_path),
        "user_goal": "inspect project",
        "status": "QUEUED",
        "created_at": "2026-06-29T01:00:00Z",
        "updated_at": "2026-06-29T01:01:00Z",
        "run_dir": str(tmp_path / "run"),
    })

    output = write_task_token_ledger(db, "task_2", tmp_path / "run" / "token_ledger.json")

    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["task_id"] == "task_2"
    assert payload["codex"]["event_count"] == 0
    assert payload["worker"]["attempts"] == 0
