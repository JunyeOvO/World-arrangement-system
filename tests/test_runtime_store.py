import subprocess
from pathlib import Path

import pytest

from orchestrator.ignore_manager import ensure_world_ignored, remove_world_ignore_block
from orchestrator.runtime_store import RuntimeStore, resolve_project_id


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=path, check=True)
    (path / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_zero_write_uses_world_home_and_does_not_write_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    world_home = tmp_path / "world-home"
    monkeypatch.setenv("WORLD_HOME", str(world_home))

    store = RuntimeStore(repo, "zero_write")
    profile_path = store.write_project_profile({"repo_name": "repo"})
    run_dir = store.resolve_run_dir("run-1")

    assert store.backend == "external-global"
    assert profile_path == world_home / "projects" / resolve_project_id(repo) / "project.profile.json"
    assert run_dir == world_home / "projects" / resolve_project_id(repo) / "runs" / "run-1"
    assert not (repo / ".world").exists()
    status = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, capture_output=True, check=True)
    assert status.stdout.strip() == ""


def test_runtime_store_rejects_unsafe_run_id_segments(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    world_home = tmp_path / "world-home"
    monkeypatch.setenv("WORLD_HOME", str(world_home))
    store = RuntimeStore(repo, "path_guard")

    with pytest.raises(ValueError):
        store.resolve_run_dir("../outside")
    with pytest.raises(ValueError):
        store.write_worker_result("run-1", "../task", {})
    with pytest.raises(ValueError):
        store.write_patch("run/1", "task-1", "diff")


def test_runtime_store_cleanup_rejects_path_traversal(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    world_home = tmp_path / "world-home"
    outside = world_home / "projects" / "outside"
    outside.mkdir(parents=True)
    marker = outside / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")
    monkeypatch.setenv("WORLD_HOME", str(world_home))
    store = RuntimeStore(repo, "cleanup_guard")

    with pytest.raises(ValueError):
        store.cleanup("../outside", mode="force")

    assert marker.exists()


def test_ignore_manager_appends_to_git_info_exclude_idempotently(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    exclude = repo / ".git" / "info" / "exclude"

    first = ensure_world_ignored(repo)
    second = ensure_world_ignored(repo)
    text = exclude.read_text(encoding="utf-8")

    assert first.changed is True
    assert second.changed is False
    assert text.count("World System local runtime") == 1
    assert ".world/" in text

    (repo / ".world").mkdir()
    status = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, capture_output=True, check=True)
    assert ".world" not in status.stdout


def test_ignore_manager_can_remove_world_block(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    ensure_world_ignored(repo)
    removed = remove_world_ignore_block(repo)
    text = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")

    assert removed.changed is True
    assert "World System local runtime" not in text
