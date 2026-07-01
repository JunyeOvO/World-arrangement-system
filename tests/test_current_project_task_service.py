from __future__ import annotations

from typing import Any

from orchestrator.current_project_task_service import CurrentProjectTaskService
from orchestrator.project_registry import ProjectMatch


def test_submit_current_project_task_returns_needs_user_when_detection_fails():
    service = CurrentProjectTaskService(
        detect_project_func=lambda **kwargs: ProjectMatch(None, 0.0, "none", True, None),
        submit_task=lambda *args, **kwargs: {"status": "SHOULD_NOT_RUN"},
    )

    result = service.submit_current_project_task("inspect", repo_path="C:/repo")

    assert result["status"] == "NEEDS_USER"
    assert result["message"] == "project could not be detected"
    assert result["match"]["matched_by"] == "none"


def test_submit_current_project_task_delegates_to_submit_task_with_protocol_fields():
    calls: list[dict[str, Any]] = []

    def submit_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {"status": "QUEUED", "task_id": "t_1"}

    service = CurrentProjectTaskService(
        detect_project_func=lambda **kwargs: ProjectMatch("project_1", 1.0, "repo_path", False, {"project_id": "project_1"}),
        submit_task=submit_task,
    )

    result = service.submit_current_project_task(
        "inspect repo",
        repo_path="C:/repo",
        risk_level="low",
        auto_execute=False,
        auto_pr=True,
        dry_run=True,
        force_worker="opencode",
        force_model="opencode_go_glm52",
        force_variant="high",
        image_paths=["a.png"],
        image_base64=["data:image/png;base64,abc"],
        task_mode="read_only",
        expected_diff=False,
        verification_policy="changed_files_only",
        read_budget_profile="quick_triage",
        read_budget={"max_files": 3},
    )

    assert result == {"status": "QUEUED", "task_id": "t_1"}
    assert calls[0]["args"] == ("project_1", "inspect repo", "low", False, True, True)
    assert calls[0]["kwargs"] == {
        "force_worker": "opencode",
        "force_model": "opencode_go_glm52",
        "force_variant": "high",
        "image_paths": ["a.png"],
        "image_base64": ["data:image/png;base64,abc"],
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget_profile": "quick_triage",
        "read_budget": {"max_files": 3},
    }
