from pathlib import Path


def test_ci_installs_all_extras_and_runs_full_pytest_failure_surface():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "uv sync --all-extras --dev" in workflow
    assert "--maxfail=1" not in workflow
    assert "uv run pytest -q --disable-warnings" in workflow


def test_install_docs_match_mcp_extra_install_command():
    readme = Path("README.md").read_text(encoding="utf-8")
    install_script = Path("scripts/install.sh").read_text(encoding="utf-8")

    assert "uv sync --all-extras --dev" in readme
    assert "uv sync --dev" not in readme
    assert "uv sync --all-extras --dev" in install_script
