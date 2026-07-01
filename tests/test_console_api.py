import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate

from orchestrator.artifacts import ArtifactStore
from orchestrator.console.api import ConsoleAPI
from orchestrator.console.queries import ConsoleQueries
from orchestrator.db import TaskDB


class StubService:
    def __init__(self, tmp_path: Path):
        self.db = TaskDB(tmp_path / "state.db")
        self.db.init()
        self.artifacts = ArtifactStore(tmp_path / "runs")
        self.cancelled: list[tuple[str, str]] = []

    def cancel_task(self, task_id: str, reason: str = ""):
        self.cancelled.append((task_id, reason))
        self.db.update_task(task_id, status="CANCELLED", updated_at="2026-06-28T00:00:01Z")
        return self.get_task_status(task_id)

    def get_task_status(self, task_id: str):
        task = self.db.get_task(task_id)
        return task or {"status": "NOT_FOUND", "task_id": task_id}

    def approve_task(self, task_id: str):
        return {"status": "approved", "task_id": task_id}

    def reject_task(self, task_id: str, reason: str = ""):
        self.cancel_task(task_id, reason)
        return {"status": "rejected", "task_id": task_id}


def _create_task(
    service: StubService,
    status: str = "EXECUTING",
    task_id: str = "task_console",
    updated_at: str = "2026-06-28T00:00:00Z",
) -> str:
    run_dir = service.artifacts.run_dir(task_id)
    service.db.create_task({
        "task_id": task_id,
        "project_id": "project-a",
        "repo_path": "C:/repo",
        "user_goal": "ship console",
        "status": status,
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": updated_at,
        "route_worker": "opencode",
        "route_model": "glm",
        "route_variant": "high",
        "run_dir": str(run_dir),
    })
    service.db.append_event(task_id, "created", None, "QUEUED", {"api_key": "fake-redacted-value"})
    service.artifacts.write_json(task_id, "route.json", {"selected_worker": "opencode"})
    service.artifacts.write_text(task_id, "final.md", "ok")
    return task_id


def _write_process_state(service: StubService, task_id: str, status: str) -> None:
    process_path = service.artifacts.run_dir(task_id) / "control" / "process.json"
    process_path.parent.mkdir(parents=True, exist_ok=True)
    process_path.write_text(
        json.dumps({
            "task_id": task_id,
            "pid": 1234,
            "status": status,
            "finished_at": "2026-06-28T00:00:02Z",
        }),
        encoding="utf-8",
    )


def _write_control_heartbeat(service: StubService, task_id: str, status: str) -> None:
    heartbeat_path = service.artifacts.run_dir(task_id) / "control" / "heartbeat.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps({
            "task_id": task_id,
            "pid": 1234,
            "status": status,
            "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }),
        encoding="utf-8",
    )


def test_console_snapshot_matches_schema_and_redacts(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service)
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    schema = json.loads(Path("schemas/console_snapshot.json").read_text(encoding="utf-8"))
    validate(payload, schema)
    assert status == 200
    assert "fake-redacted-value" not in json.dumps(payload)


def test_console_snapshot_does_not_count_stale_executing_without_heartbeat(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["running"] == 0
    assert payload["health"]["open_alerts"] == 1
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["runtime"] == {"live": False, "stale": True}
    assert task["display_status"] == "STALE_EXECUTING"
    assert task["big_status"] == "Alerts"
    assert task["console_group"] == "alerts"
    assert "no fresh heartbeat" in task["status_note"]


def test_console_snapshot_does_not_mutate_stale_executing_when_project_completed(tmp_path: Path):
    service = StubService(tmp_path)
    stale_task_id = _create_task(
        service,
        status="EXECUTING",
        task_id="task_stale",
        updated_at="2026-06-28T00:00:00Z",
    )
    _create_task(
        service,
        status="COMPLETED_WITH_PATCH",
        task_id="task_completed",
        updated_at="2026-06-28T00:10:00Z",
    )
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert any(task["task_id"] == stale_task_id for task in payload["tasks"])
    assert service.db.list_console_dismissed_task_ids() == set()
    assert all(event["event_type"] != "console.task_auto_dismissed" for event in service.db.list_events(stale_task_id))


def test_console_snapshot_does_not_evaluate_or_write_system_alerts(tmp_path: Path, monkeypatch):
    service = StubService(tmp_path)
    _create_task(service, status="EXECUTING")

    def fail_if_written(*args, **kwargs):
        raise AssertionError("snapshot must not write system alerts")

    monkeypatch.setattr(service.db, "upsert_system_alert", fail_if_written)
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["open_alerts"] == 1


def test_console_snapshot_counts_executing_with_fresh_heartbeat(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    service.db.upsert_worker_heartbeat({
        "worker_id": "worker-a",
        "task_id": task_id,
        "attempt_id": "attempt-a",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "EXECUTING",
        "phase": "EXECUTING",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["running"] == 1
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["runtime"] == {"live": True, "stale": False}
    assert task["display_status"] == "EXECUTING"
    assert task["console_group"] == "running"
    assert task["status_note"] == ""


def test_console_snapshot_counts_executing_with_fresh_control_heartbeat(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    _write_control_heartbeat(service, task_id, "running")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["running"] == 1
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["runtime"]["live"] is True
    assert task["runtime"]["control_heartbeat_status"] == "running"
    assert task["runtime"]["control_heartbeat_live"] is True
    assert task["display_status"] == "EXECUTING"
    assert task["console_group"] == "running"


def test_console_snapshot_uses_finished_worker_state_when_db_still_executing(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    _write_process_state(service, task_id, "succeeded")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["running"] == 0
    assert payload["health"]["open_alerts"] == 1
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["runtime"] == {
        "live": False,
        "stale": True,
        "process_status": "succeeded",
        "process_finished": True,
    }
    assert task["display_status"] == "STALE_EXECUTING"
    assert task["console_group"] == "alerts"
    assert "no fresh heartbeat" in task["status_note"]


def test_console_snapshot_counts_failed_worker_state_when_db_still_executing(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    _write_process_state(service, task_id, "failed")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["running"] == 0
    assert payload["health"]["failed"] == 1
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["display_status"] == "WORKER_FAILED"
    assert task["console_group"] == "failed"


def test_console_snapshot_assigns_status_groups(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="NEW", task_id="task_queued")
    _create_task(service, status="NEEDS_USER", task_id="task_approval")
    _create_task(service, status="NEEDS_REVIEW", task_id="task_review")
    _create_task(service, status="RETRYING", task_id="task_retrying")
    _create_task(service, status="FAILED_FINAL", task_id="task_failed")
    _create_task(service, status="COMPLETED_NO_CHANGES", task_id="task_done")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload["health"]["queued"] == 1
    assert payload["health"]["approval_waiting"] == 2
    assert payload["health"]["failed"] == 1
    assert payload["health"]["open_alerts"] == 1
    groups = {task["task_id"]: task["console_group"] for task in payload["tasks"]}
    assert groups["task_queued"] == "queued"
    assert groups["task_approval"] == "approval"
    assert groups["task_review"] == "approval"
    assert groups["task_retrying"] == "alerts"
    assert groups["task_failed"] == "failed"
    assert groups["task_done"] == "none"


def test_dashboard_summary_uses_derived_big_status_counts(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="EXECUTING", task_id="task_stale")
    _create_task(service, status="NEEDS_USER", task_id="task_approval")
    _create_task(service, status="FAILED_FINAL", task_id="task_failed")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/dashboard/summary")

    assert status == 200
    assert payload["counts"] == {
        "Running": 0,
        "Queued": 0,
        "Failed": 1,
        "Approval": 1,
        "Alerts": 1,
    }
    assert "updated_at" in payload


def test_dashboard_tasks_can_filter_by_big_status(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="RETRYING", task_id="task_retrying")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/dashboard/tasks", "big_status=Alerts")

    assert status == 200
    assert payload["next_cursor"] is None
    assert payload["items"] == [{
        "task_id": task_id,
        "raw_status": "RETRYING",
        "display_status": "RETRY_STUCK",
        "big_status": "Alerts",
        "project_id": "project-a",
        "goal": "ship console",
        "reason": "retry has no reliable scheduler state",
        "updated_at": "2026-06-28T00:00:00Z",
    }]


def test_task_detail_includes_lifecycle_and_artifacts(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service)
    service.artifacts.write_json(task_id, "route.json", {
        "selected_worker": "opencode",
        "selected_model": "opencode_go_glm52",
        "agent_llm": "claude code + deepseek V4 pro",
        "fallback_models": ["deepseek_pro", "mimo_v25"],
        "reason": "ClaudeCodeWorker can escalate to OpenCodeWorker with opencode-go/glm-5.2",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get(f"/api/tasks/{task_id}")

    assert status == 200
    assert payload["task"]["task_id"] == task_id
    assert payload["task"]["route"]["worker"] == "Opencode"
    assert payload["task"]["route"]["model"] == "GLM-5.2"
    assert payload["route_decision"]["selected_worker"] == "Opencode"
    assert payload["route_decision"]["selected_model"] == "GLM-5.2"
    assert payload["route_decision"]["agent_llm"] == "Claudecode + Deepseek-V4-pro"
    assert payload["route_decision"]["fallback_models"] == ["Deepseek-V4-pro", "Mimo-V2.5"]
    assert payload["route_decision"]["reason"] == "Claudecode can escalate to Opencode with GLM-5.2"
    assert payload["timeline"][0]["event_type"] == "created"
    assert payload["artifacts"][0]["url"].startswith(f"/api/tasks/{task_id}/artifacts/")


def test_task_detail_marks_stale_executing_without_heartbeat(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get(f"/api/tasks/{task_id}")

    assert status == 200
    assert payload["task"]["runtime"] == {"live": False, "stale": True}
    assert payload["task"]["display_status"] == "STALE_EXECUTING"
    assert payload["task"]["raw_status"] == "EXECUTING"
    assert payload["task"]["big_status"] == "Alerts"
    assert payload["task"]["console_group"] == "alerts"
    assert "no fresh heartbeat" in payload["task"]["status_note"]


def test_task_detail_uses_finished_worker_state_when_db_still_executing(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    _write_process_state(service, task_id, "timed_out")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get(f"/api/tasks/{task_id}")

    assert status == 200
    assert payload["task"]["runtime"]["process_status"] == "timed_out"
    assert payload["task"]["display_status"] == "WORKER_TIMED_OUT"
    assert payload["task"]["big_status"] == "Failed"


def test_artifact_whitelist_blocks_env_and_path_escape(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service)
    queries = ConsoleQueries(service.db, service.artifacts)

    status, _, body = queries.read_artifact_text(task_id, "../.env")

    assert status == 403
    assert ".env" not in body


def test_cancel_action_checks_state_machine(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="DONE")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_post(f"/api/tasks/{task_id}/cancel", b"{}")

    assert status == 409
    assert payload["status"] == "INVALID_STATE"
    assert service.cancelled == []


def test_cancel_action_calls_registered_service_and_audits(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="EXECUTING")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_post(
        f"/api/tasks/{task_id}/cancel",
        b'{"reason":"stop from console"}',
    )

    assert status == 200
    assert payload["status"] == "CANCELLED"
    assert service.cancelled == [(task_id, "stop from console")]
    events = service.db.list_events(task_id)
    assert events[-1]["event_type"] == "console.cancel_clicked"


def test_retry_action_is_explicitly_not_implemented_and_keeps_state(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="FAILED_FINAL")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_post(f"/api/tasks/{task_id}/retry", b"{}")

    assert status == 501
    assert payload["status"] == "RETRY_NOT_IMPLEMENTED"
    assert service.db.get_task(task_id)["status"] == "FAILED_FINAL"
    assert service.db.list_events(task_id)[-1]["event_type"] == "console.retry_rejected"


def test_dismiss_failed_task_removes_it_from_console_snapshot(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="FAILED_FINAL")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_post(
        f"/api/tasks/{task_id}/dismiss",
        b'{"reason":"hide from failed cards"}',
    )
    snapshot_status, _, snapshot = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert payload == {"status": "dismissed", "task_id": task_id}
    assert snapshot_status == 200
    assert snapshot["health"]["failed"] == 0
    assert all(task["task_id"] != task_id for task in snapshot["tasks"])
    assert service.db.list_events(task_id)[-1]["event_type"] == "console.task_dismissed"


def test_dismiss_approval_task_removes_it_from_console_snapshot(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="HARD_APPROVAL_WAITING")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, _ = api.handle_post(f"/api/tasks/{task_id}/dismiss", b"{}")
    _, _, snapshot = api.handle_get("/api/console/snapshot")

    assert status == 200
    assert snapshot["health"]["approval_waiting"] == 0
    assert all(task["task_id"] != task_id for task in snapshot["tasks"])


def test_dismiss_rejects_non_failed_non_approval_task(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="DONE")
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_post(f"/api/tasks/{task_id}/dismiss", b"{}")

    assert status == 409
    assert payload["status"] == "INVALID_STATE"


def test_metrics_usage_returns_cost_series_and_call_rows(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_metrics")
    service.db.upsert_task_metrics({
        "task_id": "task_metrics",
        "attempt_no": 1,
        "worker": "go",
        "model": "glm-5.2",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 0.0139,
        "duration_ms": 1200,
        "duration_api_ms": 1000,
        "num_turns": 1,
        "input_tokens": 45978,
        "output_tokens": 74,
        "cache_read_input_tokens": 0,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-28T13:12:00Z",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/metrics/usage", "limit=20")

    assert status == 200
    assert payload["cost_series"]["dates"] == ["2026-06-28"]
    assert payload["cost_series"]["models"] == ["GLM-5.2"]
    assert payload["cost_series"]["rows"] == [
        {"date": "2026-06-28", "model": "GLM-5.2", "cost_usd": 0.064695}
    ]
    assert payload["calls"][0]["worker"] == "Opencode"
    assert payload["calls"][0]["model"] == "GLM-5.2"
    assert payload["calls"][0]["input_tokens"] == 45978
    assert payload["calls"][0]["output_tokens"] == 74
    assert payload["calls"][0]["cost_usd"] == 0.064695
    assert payload["calls"][0]["session"] == "_metrics"


def test_metrics_summary_and_models_compute_cost_from_tokens(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_pricing")
    service.db.upsert_task_metrics({
        "task_id": "task_pricing",
        "attempt_no": 1,
        "worker": "claude_code",
        "model": "deepseek_pro",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 99.99,
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "num_turns": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-28T13:12:00Z",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    _, _, summary = api.handle_get("/api/metrics/summary")
    _, _, models = api.handle_get("/api/metrics/models")

    assert summary["total_cost_usd"] == 1.308625
    assert summary["priced_attempts"] == 1
    assert summary["unpriced_attempts"] == 0
    assert summary["pricing_complete"] is True
    assert models["models"][0]["worker"] == "Claudecode"
    assert models["models"][0]["model"] == "Deepseek-V4-pro"
    assert models["models"][0]["priced_attempts"] == 1
    assert models["models"][0]["unpriced_attempts"] == 0
    assert models["models"][0]["pricing_complete"] is True
    assert models["models"][0]["avg_cost_usd"] == 1.308625
    assert models["models"][0]["total_cost_usd"] == 1.308625


def test_metrics_summary_p95_duration_uses_ceil_rank(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_p95")
    for attempt_no, duration_ms in enumerate(range(100, 1100, 100), start=1):
        service.db.upsert_task_metrics({
            "task_id": "task_p95",
            "attempt_no": attempt_no,
            "worker": "claude_code",
            "model": "deepseek_flash",
            "status": "success",
            "failure_reason": "",
            "total_cost_usd": 0.0,
            "duration_ms": duration_ms,
            "duration_api_ms": duration_ms,
            "num_turns": 1,
            "input_tokens": 10,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "changed_files_count": 0,
            "build_passed": True,
            "review_approved": True,
            "created_at": f"2026-06-28T13:{attempt_no:02d}:00Z",
        })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    _, _, summary = api.handle_get("/api/metrics/summary")

    assert summary["p95_duration_ms"] == 1000


def test_metrics_reports_unpriced_models_instead_of_silent_zero_cost(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_unknown_price")
    service.db.upsert_task_metrics({
        "task_id": "task_unknown_price",
        "attempt_no": 1,
        "worker": "claude_code",
        "model": "future_model_x",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 99.99,
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "num_turns": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_input_tokens": 0,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-28T13:12:00Z",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    _, _, summary = api.handle_get("/api/metrics/summary")
    _, _, models = api.handle_get("/api/metrics/models")
    _, _, detail = api.handle_get("/api/tasks/task_unknown_price")

    assert summary["total_cost_usd"] == 0.0
    assert summary["priced_attempts"] == 0
    assert summary["unpriced_attempts"] == 1
    assert summary["pricing_complete"] is False
    assert "without configured prices" in summary["cost_note"]
    assert models["models"][0]["unpriced_attempts"] == 1
    assert models["models"][0]["pricing_complete"] is False
    assert detail["metrics"][0]["priced"] is False
    assert "missing_model_price" in detail["metrics"][0]["pricing_note"]


def test_model_metrics_merges_display_name_aliases(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_glm_a")
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_glm_b")
    for task_id, model in (
        ("task_glm_a", "opencode-go/glm-5.2"),
        ("task_glm_b", "opencode_go_glm52"),
    ):
        service.db.upsert_task_metrics({
            "task_id": task_id,
            "attempt_no": 1,
            "worker": "opencode",
            "model": model,
            "status": "success",
            "failure_reason": "",
            "total_cost_usd": 99.99,
            "duration_ms": 1000,
            "duration_api_ms": 900,
            "num_turns": 1,
            "input_tokens": 1_000,
            "output_tokens": 100,
            "cache_read_input_tokens": 500,
            "changed_files_count": 1,
            "build_passed": True,
            "review_approved": True,
            "created_at": "2026-06-28T13:12:00Z",
        })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    _, _, models = api.handle_get("/api/metrics/models")

    assert models["models"] == [{
        "worker": "Opencode",
        "model": "GLM-5.2",
        "attempts": 2,
        "priced_attempts": 2,
        "unpriced_attempts": 0,
        "pricing_complete": True,
        "avg_cost_usd": 0.00197,
        "success_rate": 1.0,
        "total_cost_usd": 0.00394,
    }]


def test_metrics_efficiency_reports_real_token_cost_and_reference_baseline(tmp_path: Path):
    service = StubService(tmp_path)
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_efficiency_low")
    _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_efficiency_high")
    service.db.upsert_task_metrics({
        "task_id": "task_efficiency_low",
        "attempt_no": 1,
        "worker": "claude_code",
        "model": "deepseek_flash",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 99.99,
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "num_turns": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 500_000,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-28T13:12:00Z",
    })
    service.db.upsert_task_metrics({
        "task_id": "task_efficiency_high",
        "attempt_no": 1,
        "worker": "opencode",
        "model": "opencode_go_glm52",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 99.99,
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "num_turns": 1,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_input_tokens": None,
        "changed_files_count": 1,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-28T13:12:00Z",
    })
    service.db.record_codex_usage_event({
        "task_id": "task_efficiency_low",
        "phase": "planning_dispatch",
        "model": "codex",
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
        "actual_codex_used": False,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-28T13:12:01Z",
        "metadata": {"measured": False},
    })
    service.db.record_codex_usage_event({
        "task_id": "task_efficiency_low",
        "phase": "world_review",
        "model": "codex",
        "input_tokens": 2000,
        "output_tokens": 500,
        "total_tokens": 2500,
        "actual_codex_used": True,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-28T13:12:02Z",
        "metadata": {"measured": False, "review_mode": "codex"},
    })
    service.db.record_task_baseline({
        "task_id": "task_efficiency_low",
        "baseline_kind": "codex_only_replay",
        "source": "replay_estimate",
        "input_tokens": 7000,
        "output_tokens": 1000,
        "total_tokens": 8000,
        "actual_codex_used": False,
        "estimation_method": "utf8_bytes_div_4",
        "created_at": "2026-06-28T13:12:03Z",
        "metadata": {},
    })
    service.db.record_task_baseline({
        "task_id": "task_efficiency_high",
        "baseline_kind": "codex_only_actual",
        "source": "manual",
        "input_tokens": 9000,
        "output_tokens": 1000,
        "total_tokens": 10000,
        "actual_codex_used": True,
        "estimation_method": "manual_actual",
        "created_at": "2026-06-28T13:12:04Z",
        "metadata": {},
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/metrics/efficiency")

    assert status == 200
    assert payload["reference_model"] == "GLM-5.2"
    assert payload["actual_cost_usd"] == 0.1694
    assert payload["reference_cost_usd"] == 1.97
    assert payload["savings_usd"] == 1.8006
    assert payload["savings_pct"] == 91.4
    assert payload["total_tokens"] == 1_600_000
    assert payload["cache_read_ratio"] == 33.33
    assert payload["unpriced_attempts"] == 0
    assert payload["pricing_complete"] is True
    assert payload["missing_token_rows"] == 1
    assert payload["codex_token_savings_measured"] is False
    assert payload["codex_token_savings_note"] != "[REDACTED]"
    assert payload["codex"]["estimated_total_tokens"] == 4000
    assert payload["codex"]["planning_dispatch_tokens"] == 1500
    assert payload["codex"]["world_review_tokens"] == 2500
    assert payload["codex"]["actual_codex_review_tokens"] == 2500
    assert payload["codex"]["actual_codex_event_count"] == 1
    assert payload["codex"]["quota_goal"]["target_multiplier"] == 3.5
    assert payload["codex"]["quota_goal"]["required_codex_reduction_pct"] == 71.43
    assert payload["baseline"]["tasks_with_baseline"] == 2
    assert payload["baseline"]["measured_tasks"] == 1
    assert payload["baseline"]["estimated_tasks"] == 1
    assert payload["baseline"]["baseline_total_tokens"] == 18000
    assert payload["baseline"]["world_codex_total_tokens"] == 4000
    assert payload["baseline"]["codex_tokens_saved"] == 14000
    assert payload["baseline"]["codex_reduction_pct"] == 77.78
    assert payload["baseline"]["claim_strength"] == "actual_codex_only_baseline"
    assert payload["baseline"]["rows"][0]["status"] == "measured"
    assert payload["by_model"][0]["model"] == "Deepseek-V4-flash"
    assert payload["by_model"][0]["pricing_complete"] is True
    assert payload["by_model"][0]["savings_usd"] == 1.8006


def test_metrics_quality_backfills_task_outcomes(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service, status="COMPLETED_WITH_PATCH", task_id="task_quality")
    service.artifacts.write_json(task_id, "task.json", {
        "task_id": task_id,
        "task_type": "read_only_analysis",
        "risk_level": "low",
    })
    service.artifacts.write_json(task_id, "verify/verify.json", {
        "tests_passed": True,
        "build_passed": True,
        "changed_files": [],
    })
    service.artifacts.write_json(task_id, "review/review.json", {
        "approved": True,
        "review_mode": "local",
    })
    service.db.upsert_task_metrics({
        "task_id": task_id,
        "attempt_no": 1,
        "worker": "claude_code",
        "model": "deepseek_flash",
        "status": "success",
        "failure_reason": "",
        "total_cost_usd": 0.0,
        "duration_ms": 100,
        "duration_api_ms": 80,
        "num_turns": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 0,
        "changed_files_count": 0,
        "build_passed": True,
        "review_approved": True,
        "created_at": "2026-06-29T00:00:00Z",
    })
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get("/api/metrics/quality")

    assert status == 200
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["success_rate"] == 100.0
    assert payload["summary"]["tests_pass_rate"] == 100.0
    assert payload["summary"]["review_approval_rate"] == 100.0
    assert payload["rows"][0]["task_id"] == task_id
    assert payload["rows"][0]["outcome"] == "success"
    assert payload["rows"][0]["tests_passed"] is True
    assert payload["rows"][0]["review_approved"] is True
    assert service.db.get_task_outcome(task_id) is not None
