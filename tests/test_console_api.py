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


def _create_task(service: StubService, status: str = "EXECUTING") -> str:
    task_id = "task_console"
    run_dir = service.artifacts.run_dir(task_id)
    service.db.create_task({
        "task_id": task_id,
        "project_id": "project-a",
        "repo_path": "C:/repo",
        "user_goal": "ship console",
        "status": status,
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:00:00Z",
        "route_worker": "opencode",
        "route_model": "glm",
        "route_variant": "high",
        "run_dir": str(run_dir),
    })
    service.db.append_event(task_id, "created", None, "QUEUED", {"api_key": "fake-redacted-value"})
    service.artifacts.write_json(task_id, "route.json", {"selected_worker": "opencode"})
    service.artifacts.write_text(task_id, "final.md", "ok")
    return task_id


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
    task = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task["runtime"] == {"live": False, "stale": True}


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


def test_task_detail_includes_lifecycle_and_artifacts(tmp_path: Path):
    service = StubService(tmp_path)
    task_id = _create_task(service)
    api = ConsoleAPI(service)  # type: ignore[arg-type]

    status, _, payload = api.handle_get(f"/api/tasks/{task_id}")

    assert status == 200
    assert payload["task"]["task_id"] == task_id
    assert payload["route_decision"]["selected_worker"] == "opencode"
    assert payload["timeline"][0]["event_type"] == "created"
    assert payload["artifacts"][0]["url"].startswith(f"/api/tasks/{task_id}/artifacts/")


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
