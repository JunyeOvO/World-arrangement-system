from orchestrator.router_explanation import blocked_route_reason, route_reason


def test_blocked_route_reason_keeps_original_reason_and_shape():
    assert (
        blocked_route_reason({"reason": "policy denied"}, "review_only")
        == "policy denied; task_shape=review_only; budget_estimate_usd=0.00"
    )


def test_route_reason_includes_selected_history_budget_decision_and_fallbacks():
    reason = route_reason(
        {
            "selected_worker": "claude_code",
            "selected_model": "deepseek_flash",
            "retry_chain": [
                {"model": "deepseek_flash"},
                {"model": "deepseek_pro"},
                {"model": "opencode-go/glm-5.2"},
            ],
        },
        "targeted_patch",
        {
            "deepseek_flash": {"success_rate": 0.95, "avg_cost": 0.01},
            "_decision": {
                "selected": "deepseek_flash",
                "scores": {"deepseek_flash": 1.0, "deepseek_pro": 0.9},
            },
        },
        budget_cap=0.10,
        estimate=0.3775,
    )

    assert "task_shape=targeted_patch" in reason
    assert "selected=claude_code/deepseek_flash" in reason
    assert "budget_estimate_usd=0.38" in reason
    assert "budget_cap_usd=0.10" in reason
    assert "history[deepseek_flash].success_rate=0.95; avg_cost=0.01" in reason
    assert "history_decision=deepseek_flash" in reason
    assert "fallback=['deepseek_pro', 'opencode-go/glm-5.2']" in reason


def test_route_reason_marks_history_without_selected_model_record():
    reason = route_reason(
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro", "retry_chain": []},
        "docs_update",
        {"deepseek_flash": {"success_rate": 0.4}},
        budget_cap=None,
        estimate=0.30,
    )

    assert "history=no_selected_model_record" in reason


def test_route_reason_marks_open_bug_hunt_flash_avoidance():
    reason = route_reason(
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro", "retry_chain": []},
        "open_bug_hunt",
        {},
        budget_cap=None,
        estimate=0.30,
    )

    assert "history=no_prior_metrics" in reason
    assert "open bug hunt avoids flash as primary" in reason
