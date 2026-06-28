import json
import subprocess
import sys

from orchestrator.verifier import verify, write_verify_result


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
