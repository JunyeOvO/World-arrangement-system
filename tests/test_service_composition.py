from __future__ import annotations

from orchestrator.scheduler import OrchestratorService
from orchestrator.service_composition import build_orchestrator_components
from orchestrator.verifier import VerifyResult
from orchestrator.workers.base import Worker, WorkerResult


class FakeWorker(Worker):
    name = "fake"

    def run(self, prompt, worktree, route, task, dry_run=False):
        return WorkerResult(status="success", summary="ok")


def _verify(task):
    return VerifyResult(tests_passed=True, build_passed=True, forbidden_allowed=True)


def test_build_orchestrator_components_creates_runtime_services(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))
    worker = FakeWorker()

    components = build_orchestrator_components(
        profile_project=lambda *args, **kwargs: {"ok": True},
        detect_project=lambda *args, **kwargs: {"project_id": "p"},
        world_create_plan=lambda *args, **kwargs: {"plan": {"route": {}}},
        submit_task=lambda *args, **kwargs: {"task_id": "t"},
        execute_task=lambda *args, **kwargs: None,
        get_task_status=lambda task_id: {"task_id": task_id},
        new_task_id=lambda: "t_factory",
        now=lambda: "now",
        dry_verify_func=_verify,
        task_requires_diff=lambda task: False,
        verify_func=lambda task, project: _verify(task),
        review_func=lambda inputs, output_path: {"approved": True},
        publish_func=lambda *args, **kwargs: {"status": "PATCH_WRITTEN"},
        build_prompt=lambda task, project, route: "prompt",
        workers={"fake": worker},
        default_worker=worker,
    )

    assert components.paths.home == tmp_path / "runtime"
    assert components.db.get_task("missing") is None
    assert components.task_submission is not None
    assert components.task_execution is not None
    assert components.execution_callbacks is not None


def test_orchestrator_service_exposes_component_facade_attributes(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path / "runtime"))

    service = OrchestratorService()

    assert service.components.db is service.db
    assert service.components.artifacts is service.artifacts
    assert service.components.task_submission is service.task_submission
    assert service.components.task_execution is service.task_execution
