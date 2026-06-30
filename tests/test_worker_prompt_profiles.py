from __future__ import annotations

from orchestrator.worker_prompt_profiles import read_only_required_output_contract, worker_profile_strategy


def test_code_contract_profile_requires_contract_template():
    task = {
        "read_budget_profile": "code_contract_audit",
        "read_budget": {"max_worker_turns": 10},
    }

    contract = read_only_required_output_contract(task, read_only=True)

    assert "suspected_contract" in contract
    assert "producer" in contract
    assert "consumer" in contract
    assert "at most 10 worker turns" in contract
    assert "changed_files: []" in contract


def test_profile_strategy_is_empty_for_non_read_only_profiles():
    assert worker_profile_strategy({"read_budget_profile": "unknown"}) == ""


def test_next_task_planning_strategy_forces_single_candidate_behavior(tmp_path):
    (tmp_path / "README.md").write_text("# Project\n## Next\n", encoding="utf-8")
    task = {
        "repo_path": str(tmp_path),
        "read_budget_profile": "next_task_planning",
    }

    strategy = worker_profile_strategy(task)

    assert "Next-task planning strategy:" in strategy
    assert "one high-confidence candidate is better than timing out" in strategy
    assert "Seed files World already selected" in strategy
