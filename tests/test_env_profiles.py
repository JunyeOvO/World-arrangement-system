from pathlib import Path

from orchestrator.env_profiles import env_for_model, parse_env_file, redacted_env_keys


def test_parse_env_file(tmp_path: Path):
    env_file = tmp_path / "provider.env"
    env_file.write_text(
        """
# comment
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN='secret'
EMPTY=
""",
        encoding="utf-8",
    )
    env = parse_env_file(env_file)
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert "ANTHROPIC_AUTH_TOKEN" in redacted_env_keys(env)


def test_env_for_model_prefers_runtime_home_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(tmp_path))
    (tmp_path / "profiles").mkdir()
    (tmp_path / "models.yaml").write_text(
        """
models:
  deepseek_pro:
    env_profile: profiles/deepseek_pro.env
""",
        encoding="utf-8",
    )
    profile = tmp_path / "profiles" / "deepseek_pro.env"
    profile.write_text("ANTHROPIC_BASE_URL=https://runtime.example\n", encoding="utf-8")

    env, path = env_for_model("deepseek_pro")

    assert path == str(profile)
    assert env["ANTHROPIC_BASE_URL"] == "https://runtime.example"
