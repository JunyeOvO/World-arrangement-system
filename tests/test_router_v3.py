from orchestrator.router import plan_route
from orchestrator.router_v3 import classify_task_shape


def test_test_runs_not_misclassified_as_test_generation():
    task = {"user_goal": "Investigate why test runs are failing in CI", "risk_level": "medium"}

    route = plan_route(task, {})

    assert route.task_shape != "test_generation"
    assert route.to_dict()["task_labels"]["task_shape"] != "test_generation"
    assert "task_shape=" in route.reason


def test_documents_field_name_not_misclassified_as_docs_update():
    task = {
        "user_goal": "Fix the serializer bug for the documents field in API responses",
        "risk_level": "medium",
        "target_paths": ["app/serializers.py"],
    }

    route = plan_route(task, {})

    assert classify_task_shape(task) == "targeted_patch"
    assert route.task_shape == "targeted_patch"
    assert route.selected_model == "deepseek_pro"


def test_open_bug_hunt_does_not_default_to_flash():
    route = plan_route(
        {"user_goal": "Find one bug and fix it", "risk_level": "medium"},
        {},
        history={
            "deepseek_flash": {"success_rate": 0.95, "avg_cost": 0.05},
            "deepseek_pro": {"success_rate": 0.9, "avg_cost": 0.3},
        },
    )

    data = route.to_dict()

    assert data["task_shape"] == "open_bug_hunt"
    assert data["selected_model"] == "deepseek_pro"
    assert data["retry_chain"][0]["model"] == "deepseek_pro"
    assert any(step["worker"] == "opencode" for step in data["retry_chain"][1:])
    assert "open bug hunt avoids flash" in data["reason"]


def test_route_decision_contains_cost_history_and_fallback():
    route = plan_route(
        {
            "user_goal": "Fix the off-by-one bug in app/ranker.py",
            "risk_level": "medium",
            "target_paths": ["app/ranker.py"],
            "budget_cap_usd": 1.0,
        },
        {},
        history=[
            {
                "model": "deepseek_pro",
                "worker": "claude_code",
                "success_rate": 0.9,
                "avg_cost_usd": 0.3,
                "attempts": 5,
            }
        ],
    )
    data = route.to_dict()

    assert data["task_shape"] == "targeted_patch"
    assert data["budget_estimate_usd"] > 0
    assert data["budget_cap_usd"] == 1.0
    assert data["history_basis"]["deepseek_pro"]["success_rate"] == 0.9
    assert data["fallback_models"]
    assert "task_shape=targeted_patch" in data["reason"]
    assert "history[deepseek_pro].success_rate=0.9" in data["reason"]


def test_docs_update_can_use_flash_only_with_good_history():
    route = plan_route(
        {"user_goal": "Update README documentation", "risk_level": "low"},
        {},
        history={"deepseek_flash": {"success_rate": 0.8, "avg_cost": 0.05}},
    )

    assert route.task_shape == "docs_update"
    assert route.selected_model == "deepseek_flash"
    assert route.retry_chain[1]["model"] == "deepseek_pro"


def test_docs_update_avoids_flash_when_history_is_poor():
    route = plan_route(
        {"user_goal": "Update README documentation", "risk_level": "low"},
        {},
        history=[
            {
                "model": "deepseek_flash",
                "worker": "claude_code",
                "success_rate": 0.25,
                "avg_cost_usd": 0.02,
                "attempts": 8,
            },
            {
                "model": "deepseek_pro",
                "worker": "claude_code",
                "success_rate": 0.9,
                "avg_cost_usd": 0.15,
                "attempts": 8,
            },
        ],
    )

    assert route.task_shape == "docs_update"
    assert route.selected_model == "deepseek_pro"
    assert route.history_basis["_decision"]["selected"] == "deepseek_pro"


def test_single_file_patch_can_use_flash_with_strong_history_and_budget():
    route = plan_route(
        {
            "user_goal": "Fix typo in app/title.ts",
            "risk_level": "low",
            "target_paths": ["app/title.ts"],
            "budget_cap_usd": 0.1,
        },
        {},
        history=[
            {
                "model": "deepseek_flash",
                "worker": "claude_code",
                "success_rate": 0.95,
                "avg_cost_usd": 0.01,
                "attempts": 12,
            },
            {
                "model": "deepseek_pro",
                "worker": "claude_code",
                "success_rate": 0.98,
                "avg_cost_usd": 0.2,
                "attempts": 12,
            },
        ],
    )

    assert route.task_shape == "targeted_patch"
    assert route.selected_model == "deepseek_flash"
    assert route.retry_chain[0]["model"] == "deepseek_flash"


def test_low_sample_history_does_not_override_default_patch_model():
    route = plan_route(
        {
            "user_goal": "Fix a small serializer bug",
            "risk_level": "low",
            "target_paths": ["app/serializer.py"],
        },
        {},
        history=[
            {
                "model": "deepseek_flash",
                "worker": "claude_code",
                "success_rate": 1.0,
                "avg_cost_usd": 0.01,
                "attempts": 1,
            }
        ],
    )

    assert route.task_shape == "targeted_patch"
    assert route.selected_model == "deepseek_pro"


def test_history_does_not_override_hard_bugfix_opencode_rule():
    route = plan_route(
        {
            "user_goal": "Fix race condition deadlock in worker scheduler",
            "risk_level": "high",
            "task_type": "hard_bugfix",
        },
        {},
        history=[
            {
                "model": "deepseek_flash",
                "worker": "claude_code",
                "success_rate": 1.0,
                "avg_cost_usd": 0.01,
                "attempts": 20,
            }
        ],
    )

    assert route.task_shape == "large_refactor"
    assert route.selected_worker == "opencode"
    assert route.selected_model == "opencode-go/glm-5.2"
