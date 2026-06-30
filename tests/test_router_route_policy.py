from orchestrator.router_route_policy import (
    fallback_models,
    normalize_variant,
    retry_chain_for_shape,
    select_for_shape,
)


def test_default_opencode_project_uses_project_variant_for_routine_tasks():
    selected = select_for_shape(
        "targeted_patch",
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        {"user_goal": "Fix a small issue", "task_type": "routine_coding"},
        {"default_worker": "opencode", "default_variant": "high"},
        {},
        None,
    )

    assert selected["selected_worker"] == "opencode"
    assert selected["variant"] == "high"
    assert selected["intensity"] == "high"


def test_goal_with_glm_forces_opencode_high_route():
    selected = select_for_shape(
        "review_only",
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        {"user_goal": "Use GLM for this analysis"},
        {},
        {},
        None,
    )

    assert selected["selected_worker"] == "opencode"
    assert selected["selected_model"] == "opencode-go/glm-5.2"
    assert selected["variant"] == "high"


def test_docs_update_uses_flash_when_route_already_selected_flash():
    selected = select_for_shape(
        "docs_update",
        {"selected_worker": "claude_code", "selected_model": "deepseek_flash"},
        {"user_goal": "Update README"},
        {},
        {},
        None,
    )

    assert selected["selected_worker"] == "claude_code"
    assert selected["selected_model"] == "deepseek_flash"
    assert selected["intensity"] == "low"


def test_single_file_target_can_use_flash_with_reliable_history_and_budget():
    selected = select_for_shape(
        "targeted_patch",
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        {
            "user_goal": "Fix typo",
            "target_paths": ["app/title.ts"],
        },
        {},
        {
            "deepseek_flash": {"success_rate": 0.95, "avg_cost": 0.01, "attempts": 12},
            "deepseek_pro": {"success_rate": 0.98, "avg_cost": 0.20, "attempts": 12},
        },
        0.10,
    )

    assert selected["selected_model"] == "deepseek_flash"
    assert selected["intensity"] == "low"


def test_retry_chain_for_targeted_patch_adds_stronger_and_opencode_fallbacks():
    chain = retry_chain_for_shape(
        "targeted_patch",
        {"selected_worker": "claude_code", "selected_model": "deepseek_flash", "intensity": "low"},
    )

    assert [step["model"] for step in chain] == [
        "deepseek_flash",
        "deepseek_pro",
        "opencode-go/glm-5.2",
    ]
    assert fallback_models(chain) == ["deepseek_pro", "opencode-go/glm-5.2"]


def test_retry_chain_for_review_only_has_no_fallback():
    chain = retry_chain_for_shape(
        "review_only",
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro", "intensity": "medium"},
    )

    assert len(chain) == 1
    assert fallback_models(chain) == []


def test_normalize_variant_filters_unknown_values():
    assert normalize_variant("HIGH") == "high"
    assert normalize_variant("default") is None
    assert normalize_variant("not-real") is None
