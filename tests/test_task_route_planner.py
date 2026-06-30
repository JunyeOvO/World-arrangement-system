import json
from pathlib import Path

from orchestrator.artifacts import ArtifactStore
from orchestrator.task_route_planner import TaskRoutePlanner


def test_route_planner_applies_route_override_for_regular_project(tmp_path: Path) -> None:
    planner = TaskRoutePlanner(
        artifacts=ArtifactStore(tmp_path / "runs"),
        model_metrics_summary=lambda: {},
        world_plan_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("unused")),
    )
    task = {
        "task_id": "t_route",
        "user_goal": "Fix small bug",
        "risk_level": "low",
        "route_override": {
            "worker": "opencode",
            "model": "opencode_go_glm52",
            "variant": "high",
        },
    }

    route = planner.route_for_task(task, {"repo": str(tmp_path / "repo")})

    assert route["selected_worker"] == "opencode"
    assert route["selected_model"] == "opencode_go_glm52"
    assert route["variant"] == "high"
    assert route["reason"].startswith("route override")


def test_route_planner_uses_world_plan_and_writes_artifacts(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "runs")
    seen_args = []

    def world_plan_factory(repo: str, goal: str, risk_level: str, write_policy: str):
        seen_args.append((repo, goal, risk_level, write_policy))
        return {
            "plan": {
                "route": {
                    "selected_worker": "claude_code",
                    "selected_model": "deepseek_pro",
                    "fallback_models": [],
                    "max_retries": 1,
                },
                "write_policy": write_policy,
            },
            "plan_path": str(tmp_path / "world" / "plan.json"),
            "runtime_store": str(tmp_path / "world" / "store"),
        }

    planner = TaskRoutePlanner(
        artifacts=artifacts,
        model_metrics_summary=lambda: {},
        world_plan_factory=world_plan_factory,
    )
    task = {
        "task_id": "t_world_route",
        "user_goal": "Read-only audit project status",
        "risk_level": "low",
        "task_mode": "read_only",
        "expected_diff": False,
        "verification_policy": "changed_files_only",
        "read_budget_profile": "quick_triage",
        "read_budget": {"max_worker_turns": 4},
        "route_override": {"model": "deepseek_flash"},
    }
    project = {
        "repo": str(tmp_path / "repo"),
        "world": {"enabled": True, "write_policy": "zero_write"},
    }

    route = planner.route_for_task(task, project)

    assert seen_args == [(project["repo"], task["user_goal"], "low", "zero_write")]
    assert route["selected_worker"] == "claude_code"
    assert route["selected_model"] == "deepseek_flash"
    assert route["max_turns"] == 4
    plan = json.loads(artifacts.path("t_world_route", "world_plan.json").read_text(encoding="utf-8"))
    ref = json.loads(artifacts.path("t_world_route", "world_plan_ref.json").read_text(encoding="utf-8"))
    assert plan["route"] == route
    assert plan["task_mode"] == "read_only"
    assert plan["read_budget_profile"] == "quick_triage"
    assert ref["plan_path"].endswith("plan.json")
    assert ref["runtime_store"].endswith("store")
