import json
import subprocess
import sys

from orchestrator.verifier import run_commands, verify, write_verify_result


def _git_repo(path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=path, check=True)
    (path / "app.py").write_text("print('before')\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_verify_writes_structured_result_for_empty_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)
    (repo / "app.py").write_text("print('after')\n", encoding="utf-8")

    result = verify(repo, [], [f"{sys.executable} -c \"print('ok')\""], tmp_path / "verify")
    output = write_verify_result(result, tmp_path / "verify" / "verify.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["tests_passed"] is True
    assert payload["build_passed"] is True
    assert payload["forbidden_allowed"] is True
    assert payload["commands"][0]["kind"] == "build"
    assert payload["changed_files"] == ["app.py"]
    assert payload["diff_path"].endswith("diff.patch")
    assert payload["finished_at"]


def test_verify_marks_build_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)

    result = verify(repo, [], [f"{sys.executable} -c \"raise SystemExit(2)\""], tmp_path / "verify")

    assert result.tests_passed is True
    assert result.build_passed is False
    assert result.command_results[0].returncode == 2


def test_run_commands_blocks_denied_command_before_subprocess(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("denied verifier command must not execute")

    monkeypatch.setattr(subprocess, "run", fake_run)

    results = run_commands(
        repo,
        ["git push origin main"],
        tmp_path / "verify" / "test.log",
        kind="test",
        permission_worker="claude_code",
    )

    assert calls == []
    assert results[0].returncode == 126
    assert results[0].permission_allowed is False
    assert "git push" in results[0].permission_reason


def test_verify_marks_permission_block_as_forbidden_not_executed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)

    result = verify(
        repo,
        ["git push origin main"],
        [],
        tmp_path / "verify",
        permission_worker="opencode",
    )

    assert result.tests_passed is False
    assert result.forbidden_allowed is True
    assert result.command_permissions_allowed is False
    assert result.command_results[0].returncode == 126
    assert result.command_results[0].permission_allowed is False
