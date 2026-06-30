import json

from orchestrator.failure_classifier import (
    classify_review_failure,
    classify_verify_failure,
    classify_worker_failure,
)


def test_classifies_max_turns_without_diff(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(json.dumps({"type": "result", "subtype": "error_max_turns"}) + "\n", encoding="utf-8")

    result = classify_worker_failure(status="failed", stdout_path=str(stream), changed_files=[])

    assert result.failure_reason == "max_turns_no_diff"
    assert result.retryable is True
    assert result.recommended_action == "escalate_model_or_narrow_task"


def test_classifies_max_turns_with_diff(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(json.dumps({"type": "result", "subtype": "error_max_turns"}) + "\n", encoding="utf-8")

    result = classify_worker_failure(status="failed", stdout_path=str(stream), changed_files=["app.py"])

    assert result.failure_reason == "max_turns_with_diff"
    assert result.recommended_action == "verify_partial_patch"


def test_classifies_ignored_early_output_marker(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(
        "\n".join([
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "I have enough data to compile the contract audit. Let me verify one more detail.",
                        }
                    ]
                },
            }),
            json.dumps({"type": "result", "subtype": "error_max_turns"}),
        ]) + "\n",
        encoding="utf-8",
    )

    result = classify_worker_failure(status="failed", stdout_path=str(stream), changed_files=[])

    assert result.failure_reason == "worker_ignored_early_output"
    assert result.recommended_action == "enforce_partial_result_template"
    assert "stream_marker=enough_data_without_final" in result.evidence


def test_classifies_auth_and_command_errors():
    auth = classify_worker_failure(status="failed", summary="401 unauthorized")
    missing = classify_worker_failure(status="failed", summary="program not found")

    assert auth.failure_reason == "auth_failed"
    assert auth.retryable is False
    assert missing.failure_reason == "command_missing"
    assert missing.retryable is False


def test_classifies_verify_and_review_failures():
    build = classify_verify_failure(tests_passed=True, build_passed=False, forbidden_allowed=True)
    forbidden = classify_verify_failure(tests_passed=True, build_passed=True, forbidden_allowed=False)
    dangerous_command = classify_verify_failure(
        tests_passed=False,
        build_passed=True,
        forbidden_allowed=True,
        command_permissions_allowed=False,
        evidence=["bash denied by pattern: git push*"],
    )
    review = classify_review_failure({"approved": False, "available": False, "error": "timeout"})

    assert build.failure_reason == "build_failed"
    assert forbidden.failure_reason == "forbidden_path"
    assert dangerous_command.failure_reason == "dangerous_command"
    assert dangerous_command.retryable is False
    assert review.failure_reason == "review_unavailable"
