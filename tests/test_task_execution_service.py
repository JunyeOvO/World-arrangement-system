from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from orchestrator.artifacts import ArtifactStore
from orchestrator.db import TaskDB
from orchestrator.task_execution_gate import StatusTransition
from orchestrator.task_execution_service import TaskExecutionService


class FakeGate:
    def __init__(self, result):
        self.result = result

    def run(self, task, project):
        return self.result


class FakeRoutePlanner:
    def __init__(self, route: dict[str, Any]):
        self.route = route
        self.calls = []

    def route_for_task(self, task, project):
        self.calls.append((task, project))
        return dict(self.route)


class FakePreparation:
    def __init__(self, worktree_path: Path):
        self.worktree_path = worktree_path
        self.calls = []

    def prepare(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(worktree=SimpleNamespace(path=str(self.worktree_path), branch="ai/t_exec"))


class FakeAttemptRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeCompletionPipeline:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)


def _task(tmp_path: Path) -> dict[str, Any]:
    run_dir = tmp_path / "runs" / "t_exec"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "task_id": "t_exec",
        "run_dir": str(run_dir),
        "project_id": "proj",
        "user_goal": "inspect project",
        "risk_level": "low",
        "read_budget": {"max_worker_turns": 3},
    }


def _db(tmp_path: Path, task: dict[str, Any]) -> TaskDB:
    db = TaskDB(tmp_path / "state.db")
    db.init()
    db.create_task({
        "task_id": task["task_id"],
        "project_id": task["project_id"],
        "repo_path": str(tmp_path / "repo"),
        "user_goal": task["user_goal"],
        "status": "QUEUED",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
        "run_dir": task["run_dir"],
    })
    return db


def _service(tmp_path: Path, *, gate_result, attempt_result):
    task = _task(tmp_path)
    db = _db(tmp_path, task)
    statuses = []
    policies = []
    completion = FakeCompletionPipeline()
    service = TaskExecutionService(
        db=db,
        artifacts=ArtifactStore(tmp_path / "runs"),
        execution_gate=FakeGate(gate_result),
        route_planner=FakeRoutePlanner({"selected_worker": "claude_code", "selected_model": "deepseek_pro", "variant": "default"}),
        preparation=FakePreparation(tmp_path / "worktree"),
        attempt_runner=FakeAttemptRunner(attempt_result),
        completion_pipeline=completion,
        set_status=lambda task_id, status, event, payload: statuses.append((task_id, status, event, payload)),
        record_policy_learning=lambda *args, **kwargs: policies.append((args, kwargs)),
        now=lambda: "2026-07-01T00:00:01Z",
    )
    return service, task, db, statuses, policies, completion


def test_execution_service_records_policy_incident_when_gate_blocks(tmp_path: Path):
    gate_result = SimpleNamespace(
        continue_execution=False,
        transitions=[StatusTransition("FAILED_FINAL", "risk_blocked", {"allowed": False})],
        policy_incident=True,
    )
    attempt_result = SimpleNamespace(completed=False)
    service, task, _, statuses, policies, completion = _service(tmp_path, gate_result=gate_result, attempt_result=attempt_result)

    service.execute(task, {"repo": str(tmp_path)})

    assert statuses == [("t_exec", "FAILED_FINAL", "risk_blocked", {"allowed": False})]
    assert policies[-1][1] == {"success": False, "incident": True}
    assert completion.calls == []


def test_execution_service_runs_route_prepare_attempt_and_completion(tmp_path: Path):
    gate_result = SimpleNamespace(continue_execution=True, transitions=[], policy_incident=False)
    worker_result = SimpleNamespace(status="success", summary="done")
    attempt_result = SimpleNamespace(
        completed=True,
        terminal_status=None,
        final_result=worker_result,
        last_attempt={"worker": "claude_code", "model": "deepseek_pro"},
    )
    service, task, db, statuses, _, completion = _service(tmp_path, gate_result=gate_result, attempt_result=attempt_result)

    service.execute(task, {"repo": str(tmp_path)}, dry_run=True)

    route = json.loads((Path(task["run_dir"]) / "route.json").read_text(encoding="utf-8"))
    assert route["selected_worker"] == "claude_code"
    assert route["max_turns"] == 3
    db_task = db.get_task("t_exec") or {}
    assert db_task["route_worker"] == "claude_code"
    assert statuses[0][1:3] == ("ROUTED", "routed")
    assert completion.calls[0]["worker_result"] is worker_result
    assert completion.calls[0]["dry_run"] is True


def test_execution_service_records_attempt_policy_signal_when_attempt_stops(tmp_path: Path):
    gate_result = SimpleNamespace(continue_execution=True, transitions=[], policy_incident=False)
    policy_signal = SimpleNamespace(success=False, worker="claude_code", model="deepseek_pro", rollback=True, incident=True)
    attempt_result = SimpleNamespace(
        completed=False,
        terminal_status="FAILED_FINAL",
        terminal_event="worker_failed",
        terminal_payload={"failure": "boom"},
        policy_signal=policy_signal,
    )
    service, task, _, statuses, policies, completion = _service(tmp_path, gate_result=gate_result, attempt_result=attempt_result)

    service.execute(task, {"repo": str(tmp_path)})

    assert statuses[-1] == ("t_exec", "FAILED_FINAL", "worker_failed", {"failure": "boom"})
    assert policies[-1][1] == {
        "success": False,
        "worker": "claude_code",
        "model": "deepseek_pro",
        "rollback": True,
        "incident": True,
    }
    assert completion.calls == []
