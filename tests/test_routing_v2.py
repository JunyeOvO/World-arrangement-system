from orchestrator.router import plan_route
from orchestrator.agent_llm import agent_llm_name


def test_readme_architecture_description_routes_to_docs():
    route = plan_route(
        {
            "user_goal": "在 README.md 中添加项目架构说明",
            "risk_level": "medium",
            "target_paths": ["README.md"],
        },
        {},
    )

    assert route.selected_worker == "claude_code"
    assert route.selected_model == "deepseek_pro"
    assert route.task_labels["artifact_type"] == "docs"
    assert "docs" in route.task_labels["risk_domain"]
    assert "opencode" in {c["worker"] for c in route.rejected_candidates}


def test_readme_auth_flow_docs_not_high_risk():
    route = plan_route(
        {
            "user_goal": "Update docs/auth.md with the auth login flow",
            "risk_level": "medium",
            "target_paths": ["docs/auth.md"],
        },
        {},
    )

    assert route.selected_worker == "claude_code"
    assert route.task_labels["artifact_type"] == "docs"
    assert route.task_labels["risk_domain"] == ["docs"]
    assert route.requires_hard_approval is False


def test_auth_refactor_routes_high_risk_with_opencode_retry():
    route = plan_route(
        {"user_goal": "refactor auth session middleware", "risk_level": "high"},
        {},
    )

    assert route.selected_worker == "claude_code"
    assert route.selected_model == "deepseek_pro"
    assert "auth" in route.task_labels["risk_domain"]
    assert any(step["worker"] == "opencode" for step in route.retry_chain)


def test_explicit_glm52_routes_to_opencode_high():
    route = plan_route(
        {"user_goal": "Use GLM-5.2 to refactor auth session middleware", "risk_level": "high"},
        {},
    )

    assert route.selected_worker == "opencode"
    assert route.selected_model == "opencode-go/glm-5.2"
    assert route.variant == "high"


def test_project_default_model_does_not_override_opencode_route():
    route = plan_route(
        {"user_goal": "Use GLM-5.2 to analyze architecture refactor options", "risk_level": "medium"},
        {
            "stack": ["android", "python"],
            "default_worker": "claude_code",
            "default_model": "deepseek_pro",
        },
    )

    assert route.selected_worker == "opencode"
    assert route.selected_model == "opencode-go/glm-5.2"
    assert route.variant == "high"


def test_screenshot_analysis_routes_to_claude_mimo_v25():
    route = plan_route(
        {"user_goal": "Analyze UI screenshot layout issues", "risk_level": "medium"},
        {},
    )

    assert route.selected_worker == "claude_code"
    assert route.selected_model == "mimo_v25"


def test_project_default_model_does_not_override_claude_mimo_route():
    route = plan_route(
        {"user_goal": "Analyze UI screenshot layout issues", "risk_level": "medium"},
        {
            "stack": ["android", "python"],
            "default_worker": "claude_code",
            "default_model": "deepseek_pro",
        },
    )

    assert route.selected_worker == "claude_code"
    assert route.selected_model == "mimo_v25"


def test_screenshot_to_code_routes_to_claude_mimo_v25_pro():
    route = plan_route(
        {"user_goal": "Modify frontend code based on the UI screenshot", "risk_level": "medium"},
        {},
    )

    assert route.selected_worker == "claude_code"
    assert route.selected_model == "mimo_v25_pro"


def test_prod_migration_requires_hard_approval():
    route = plan_route(
        {
            "user_goal": "modify prod migration",
            "risk_level": "medium",
            "target_paths": ["database/migrations/prod/001.sql"],
        },
        {},
    )

    assert route.requires_hard_approval is True
    assert route.blocked is False


def test_env_file_target_is_blocked_before_routing():
    route = plan_route(
        {
            "user_goal": "Use GLM-5.2 to edit .env.local",
            "risk_level": "high",
            "target_paths": [".env.local"],
        },
        {},
    )

    assert route.blocked is True
    assert route.selected_worker == ""
    assert "Blocked" in route.reason or "BLOCKED" in route.reason


def test_negative_env_constraint_does_not_block_routing():
    route = plan_route(
        {
            "user_goal": "Find and fix one bug. Do not modify secrets, local.properties, .env files, or unrelated dirty work.",
            "risk_level": "medium",
        },
        {},
    )

    assert route.blocked is False
    assert route.selected_worker == "claude_code"


def test_route_contains_explanation_fields():
    route = plan_route({"user_goal": "Update README documentation", "risk_level": "low"}, {})
    data = route.to_dict()

    assert data["confidence"] > 0
    assert data["selected_agent"] == data["selected_worker"]
    assert data["selected_llm"] == data["selected_model"]
    assert data["agent_llm"] == "claude code + deepseek V4 pro"
    assert data["capability_tier"] == "default"
    assert data["capability_profile"]["context_policy"] == "top"
    assert data["capability_profile"]["context_budget"] == "max_available"
    assert data["task_labels"]["artifact_type"] == "docs"
    assert data["matched_rules"]
    assert "rejected_candidates" in data
    assert data["retry_chain"]


def test_route_agent_llm_names_cover_allowed_combinations():
    cases = [
        (
            {"user_goal": "Update README documentation", "risk_level": "low"},
            {"prefer_low_cost_for_docs": True, "default_worker": "claude_code", "default_model": "deepseek_flash", "stack": ["python", "react"]},
            "claude code + deepseek V4 flash",
        ),
        (
            {"user_goal": "Analyze project state only", "risk_level": "low"},
            {},
            "claude code + deepseek V4 pro",
        ),
        (
            {"user_goal": "Analyze UI screenshot layout issues", "risk_level": "medium"},
            {},
            "claude code + Mimo V2.5",
        ),
        (
            {"user_goal": "Modify frontend code based on the UI screenshot", "risk_level": "medium"},
            {},
            "claude code + Mimo V2.5 pro",
        ),
        (
            {"user_goal": "Use GLM-5.2 to analyze architecture refactor options", "risk_level": "medium"},
            {},
            "opencode + GLM 5.2",
        ),
    ]
    for task, project, expected in cases:
        assert plan_route(task, project).to_dict()["agent_llm"] == expected
    assert agent_llm_name("codex_review", "codex_reviewer") == "codex + GPT 5.5"
