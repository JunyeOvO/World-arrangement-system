from orchestrator.codex_usage import (
    TOKEN_ESTIMATION_METHOD,
    build_codex_usage_event,
    estimate_payload_tokens,
    estimate_text_tokens,
)


def test_estimate_text_tokens_uses_utf8_bytes():
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("中文") == 2


def test_build_codex_usage_event_sums_input_and_output_tokens():
    event = build_codex_usage_event(
        task_id="task_1",
        phase="planning_dispatch",
        input_payload={"goal": "fix bug"},
        output_payload={"task_id": "task_1", "status": "QUEUED"},
        actual_codex_used=False,
    )

    assert event["task_id"] == "task_1"
    assert event["phase"] == "planning_dispatch"
    assert event["estimation_method"] == TOKEN_ESTIMATION_METHOD
    assert event["input_tokens"] == estimate_payload_tokens({"goal": "fix bug"})
    assert event["output_tokens"] == estimate_payload_tokens({"task_id": "task_1", "status": "QUEUED"})
    assert event["total_tokens"] == event["input_tokens"] + event["output_tokens"]
