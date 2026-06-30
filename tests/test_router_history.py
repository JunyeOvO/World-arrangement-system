from orchestrator.router_history import (
    choose_claude_model,
    estimate_route_cost,
    float_or_none,
    normalize_history,
)


def test_normalize_history_accepts_list_and_aliases_avg_cost():
    history = normalize_history(
        [
            {
                "worker": "claude_code",
                "model": "deepseek_flash",
                "success_rate": "0.8",
                "avg_cost_usd": "0.02",
                "attempts": "5",
            }
        ]
    )

    assert history == {
        "deepseek_flash": {
            "success_rate": 0.8,
            "avg_cost": 0.02,
            "attempts": 5,
            "worker": "claude_code",
            "model": "deepseek_flash",
        }
    }


def test_normalize_history_accepts_dict_and_ignores_invalid_rows():
    history = normalize_history(
        {
            "deepseek_pro": {
                "worker": "claude_code",
                "success_rate": 0.9,
                "avg_cost": 0.3,
                "attempts": 10,
            },
            "broken": "not-a-row",
        }
    )

    assert set(history) == {"deepseek_pro"}
    assert history["deepseek_pro"]["model"] == "deepseek_pro"
    assert history["deepseek_pro"]["avg_cost"] == 0.3


def test_low_sample_history_does_not_override_default_model():
    history = normalize_history(
        [
            {
                "model": "deepseek_flash",
                "success_rate": 1.0,
                "avg_cost_usd": 0.01,
                "attempts": 1,
            }
        ]
    )

    selected = choose_claude_model(
        history,
        ["deepseek_flash", "deepseek_pro"],
        default="deepseek_pro",
        budget_cap=None,
        allow_low_cost=True,
    )

    assert selected == "deepseek_pro"
    assert "_decision" not in history


def test_budget_cap_can_force_low_cost_model_with_reliable_history():
    history = normalize_history(
        [
            {
                "model": "deepseek_flash",
                "success_rate": 0.95,
                "avg_cost_usd": 0.01,
                "attempts": 12,
            },
            {
                "model": "deepseek_pro",
                "success_rate": 0.98,
                "avg_cost_usd": 0.20,
                "attempts": 12,
            },
        ]
    )

    selected = choose_claude_model(
        history,
        ["deepseek_flash", "deepseek_pro"],
        default="deepseek_pro",
        budget_cap=0.10,
        allow_low_cost=True,
    )

    assert selected == "deepseek_flash"
    assert history["_decision"]["selected"] == "deepseek_flash"
    assert history["_decision"]["scores"]["deepseek_flash"] > 0


def test_estimate_route_cost_counts_fallbacks_at_reduced_weight():
    assert estimate_route_cost(
        [
            {"model": "deepseek_flash"},
            {"model": "deepseek_pro"},
            {"model": "opencode-go/glm-5.2"},
        ]
    ) == 0.3775


def test_float_or_none_handles_unparseable_values():
    assert float_or_none("1.25") == 1.25
    assert float_or_none("not-a-number") is None
    assert float_or_none(None) is None
