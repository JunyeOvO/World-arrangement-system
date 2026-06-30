from __future__ import annotations

from orchestrator.task_result_document import build_final_markdown


def test_final_markdown_renders_normal_task_result():
    markdown = build_final_markdown(
        {"user_goal": "fix login", "project_id": "demo"},
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
        {"summary": "Fixed the issue."},
        {"tests_passed": True, "build_passed": True},
        {"review_mode": "codex", "approved": True, "can_create_pr": False},
    )

    assert markdown.startswith("# Task Result")
    assert "- Task: fix login" in markdown
    assert "- Worker: claude_code" in markdown
    assert "- Status: completed" in markdown
    assert "Fixed the issue." in markdown
    assert "- Verdict: approved" in markdown
    assert "V1 never auto-merges PRs." in markdown


def test_final_markdown_marks_degraded_mock_result():
    markdown = build_final_markdown(
        {"user_goal": "audit project", "project_id": "demo"},
        {"selected_worker": "claude_code", "selected_model": "deepseek_flash"},
        {"summary": "Mock fallback.", "mock_result": True, "degradation_reason": "worker unavailable"},
        {"tests_passed": True, "build_passed": True},
        {"review_mode": "degraded_mock", "degraded": True, "can_create_pr": False},
    )

    assert "- Status: degraded_mock_result" in markdown
    assert "## Degraded Result" in markdown
    assert "- Reason: worker unavailable" in markdown
    assert "- Review verdict: not approved for publish" in markdown
