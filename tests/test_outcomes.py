from orchestrator.outcomes import derive_task_outcome, summarize_outcomes


def test_derive_successful_verified_task_outcome():
    row = derive_task_outcome(
        {
            "task_id": "task_ok",
            "project_id": "travel_with_me",
            "status": "COMPLETED_WITH_PATCH",
            "route_worker": "opencode",
            "route_model": "opencode_go_glm52",
            "created_at": "2026-06-29T00:00:00Z",
            "updated_at": "2026-06-29T00:01:00Z",
            "user_goal": "修复 UI bug",
        },
        metrics=[{"changed_files_count": 2, "build_passed": True, "review_approved": True}],
        task_artifact={"task_type": "ui", "risk_level": "medium"},
        verify={"tests_passed": True, "build_passed": True, "changed_files": ["a.js", "b.css"]},
        review={"approved": True, "review_mode": "codex"},
        result={"changed_files": ["a.js", "b.css"]},
    )

    assert row["outcome"] == "success"
    assert row["quality_state"] == "verified"
    assert row["user_acceptance"] == "accepted"
    assert row["changed_files_count"] == 2
    assert row["codex_rework_required"] is False


def test_degraded_mock_requires_rework():
    row = derive_task_outcome(
        {"task_id": "task_mock", "project_id": "p", "status": "NEEDS_USER", "user_goal": "audit"},
        review={"approved": False, "degraded": True, "review_mode": "local_fallback"},
        result={"mock_result": True},
    )

    assert row["outcome"] == "approval"
    assert row["quality_state"] == "degraded"
    assert row["user_acceptance"] == "rejected"
    assert row["codex_rework_required"] is True


def test_partial_artifacts_count_as_successful_read_only_outcome():
    row = derive_task_outcome(
        {
            "task_id": "task_partial",
            "project_id": "travel_with_me",
            "status": "COMPLETED_WITH_PARTIAL_ARTIFACTS",
            "route_worker": "claude_code",
            "route_model": "deepseek_pro",
            "user_goal": "只读分析项目质量",
        },
        review={"approved": True, "review_mode": "skipped_read_only"},
        result={"partial_result": True, "changed_files": []},
    )

    assert row["outcome"] == "success"
    assert row["quality_state"] == "unknown"
    assert row["user_acceptance"] == "accepted"


def test_success_without_explicit_verification_is_not_marked_verified():
    row = derive_task_outcome(
        {
            "task_id": "task_unverified",
            "project_id": "travel_with_me",
            "status": "COMPLETED_WITH_ARTIFACTS",
            "user_goal": "只读分析项目质量",
        },
        review={"approved": True, "review_mode": "skipped_read_only"},
        result={"changed_files": []},
    )

    assert row["outcome"] == "success"
    assert row["tests_passed"] is None
    assert row["build_passed"] is None
    assert row["review_approved"] is True
    assert row["quality_state"] == "unknown"


def test_build_metric_does_not_stand_in_for_test_result():
    row = derive_task_outcome(
        {
            "task_id": "task_build_only",
            "project_id": "travel_with_me",
            "status": "COMPLETED_WITH_PATCH",
            "user_goal": "修复 UI bug",
        },
        metrics=[{"changed_files_count": 1, "build_passed": True, "review_approved": True}],
        review={"approved": True},
        result={"changed_files": ["a.ts"]},
    )

    assert row["outcome"] == "success"
    assert row["tests_passed"] is None
    assert row["build_passed"] is True
    assert row["review_approved"] is True
    assert row["quality_state"] == "unknown"


def test_summarize_outcomes_rates():
    summary = summarize_outcomes([
        {"outcome": "success", "tests_passed": True, "review_approved": True, "user_acceptance": "accepted"},
        {"outcome": "failed", "codex_rework_required": True, "user_acceptance": "rejected"},
    ])

    assert summary["total"] == 2
    assert summary["success_rate"] == 50.0
    assert summary["known_acceptance_rate"] == 50.0
    assert summary["rework_rate"] == 50.0
