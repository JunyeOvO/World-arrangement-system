from __future__ import annotations

from orchestrator.db import TaskDB
from orchestrator.policy_learning import PolicyLearningRecorder


def test_policy_learning_recorder_records_task_completion(tmp_path):
    db = TaskDB(tmp_path / "state.sqlite")
    recorder = PolicyLearningRecorder(db)

    recorder.record_task_completion(
        {"task_id": "t_policy", "project_id": "p1", "task_type": "simple_bugfix", "risk_level": "low"},
        {"project_id": "p1"},
        success=True,
        worker="claude_code",
        model="deepseek_pro",
        tests_passed=True,
        codex_review_approved=True,
        changed_paths=["src/app.py"],
    )

    history = db.get_approval_history("p1")
    assert len(history) == 1
    assert history[0]["task_id"] == "t_policy"
    assert history[0]["worker"] == "claude_code"
    assert history[0]["model"] == "deepseek_pro"
    assert history[0]["tests_passed"] == 1
