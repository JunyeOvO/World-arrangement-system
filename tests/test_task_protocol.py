from orchestrator.task_protocol import (
    apply_read_budget_to_route,
    normalize_task_protocol,
    verification_commands_for_policy,
)


def test_frontmatter_protocol_overrides_goal_keywords():
    protocol = normalize_task_protocol(
        """task_mode: read_only
expected_diff: false
verification_policy: changed_files_only
read_budget_profile: code_contract_audit
read_budget.max_files: 5
read_budget.max_worker_turns: 4

目标：输出修复计划，不修改文件。
"""
    )

    assert protocol["task_mode"] == "read_only"
    assert protocol["expected_diff"] is False
    assert protocol["verification_policy"] == "changed_files_only"
    assert protocol["read_budget_profile"] == "code_contract_audit"
    assert protocol["read_budget"]["max_files"] == 5
    assert protocol["read_budget"]["max_worker_turns"] == 4


def test_named_profile_supplies_budget_and_explicit_budget_overrides():
    protocol = normalize_task_protocol(
        "只读调查 3D workArea 数据契约风险",
        read_budget_profile="code_contract_audit",
        read_budget={"max_files": 7},
    )

    assert protocol["read_budget_profile"] == "code_contract_audit"
    assert protocol["read_budget"]["max_files"] == 7
    assert protocol["read_budget"]["max_worker_turns"] == 10
    assert protocol["read_budget"]["max_duration_sec"] == 150


def test_budget_profile_is_inferred_from_goal_shape():
    contract = normalize_task_protocol("只读调查 3D workArea 数据契约风险")
    planning = normalize_task_protocol("挑选下一轮 World 真实小修的候选任务")
    docs = normalize_task_protocol("评估 README onboarding 缺口")

    assert contract["read_budget_profile"] == "code_contract_audit"
    assert planning["read_budget_profile"] == "next_task_planning"
    assert docs["read_budget_profile"] == "docs_review"


def test_patch_mode_defaults_to_full_verification_and_diff():
    protocol = normalize_task_protocol("Fix the serializer bug")

    assert protocol["task_mode"] == "patch"
    assert protocol["expected_diff"] is True
    assert protocol["verification_policy"] == "full"


def test_verification_policy_selects_commands():
    tests = ["npm test", "npm run check"]
    builds = ["npm run build"]

    assert verification_commands_for_policy("none", tests, builds) == ([], [])
    assert verification_commands_for_policy("changed_files_only", tests, builds) == ([], [])
    assert verification_commands_for_policy("unit", tests, builds) == (["npm test"], [])
    assert verification_commands_for_policy("full", tests, builds) == (tests, builds)


def test_read_budget_applies_route_limits_without_overwriting_explicit_route():
    route = {"selected_worker": "claude_code", "selected_model": "deepseek_flash", "timeout_sec": 30}
    task = {"read_budget": {"max_worker_turns": 3, "max_duration_sec": 60}}

    updated = apply_read_budget_to_route(route, task)

    assert updated["max_turns"] == 3
    assert updated["timeout_sec"] == 30
