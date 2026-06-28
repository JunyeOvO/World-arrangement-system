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
