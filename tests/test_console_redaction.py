from orchestrator.console.redaction import redact


def test_redacts_secret_keys_and_values():
    payload = {
        "api_key": "fake-redacted-value",
        "nested": {"authorization": "Bearer abcdefghijklmnopqrstuvwxyz"},
        "message": "token Bearer abcdefghijklmnopqrstuvwxyz should not render",
    }

    result = redact(payload)

    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["authorization"] == "[REDACTED]"
    assert "[REDACTED]" in result["message"]
    assert "abcdefghijklmnopqrstuvwxyz" not in str(result)


def test_redacts_env_paths():
    assert redact("C:/repo/.env") == "[REDACTED_PATH]"


def test_preserves_numeric_metric_token_counts():
    payload = {
        "input_tokens": 45978,
        "output_tokens": 74,
        "cache_read_input_tokens": 0,
        "auth_token": "Bearer abcdefghijklmnopqrstuvwxyz",
    }

    result = redact(payload)

    assert result["input_tokens"] == 45978
    assert result["output_tokens"] == 74
    assert result["cache_read_input_tokens"] == 0
    assert result["auth_token"] == "[REDACTED]"
