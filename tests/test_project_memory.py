import json
from pathlib import Path

from orchestrator.project_memory import ensure_project_memory


def test_project_memory_builds_redacted_cache_and_reuses_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    src = repo / "orchestrator"
    src.mkdir()
    (src / "scheduler.py").write_text(
        "API_KEY='sk-redactthisvalue123456'\n\ndef run_task():\n    pass\n",
        encoding="utf-8",
    )
    (src / "bundle.py").write_text("x" * 300_001, encoding="utf-8")
    project = {
        "repo": str(repo),
        "stack": ["python"],
        "test_commands": ["uv run pytest"],
        "forbidden_paths": [".env"],
        "world": {"write_policy": "zero_write"},
    }

    first = ensure_project_memory("demo", project)
    second = ensure_project_memory("demo", project)

    memory_path = Path(first["path"])
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    paths = {item["path"] for item in memory["files"]}

    assert memory_path.exists()
    assert "orchestrator/scheduler.py" in paths
    assert "orchestrator/bundle.py" not in paths
    assert "sk-redactthisvalue" not in first["prompt"]
    assert "API_KEY=[REDACTED]" in first["prompt"]
    assert first["memory"]["stats"]["miss_count"] >= 1
    assert first["memory"]["source_kind"] == "registered_repo"
    assert first["memory"]["source_path"] == str(repo.resolve())
    assert "Source: registered_repo" in first["prompt"]
    assert "active worktree" in first["prompt"]
    assert second["memory"]["stats"]["hit_count"] >= 1
    assert "## Project Memory" in second["prompt"]


def test_project_memory_can_be_built_from_worktree_source(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_HOME", str(tmp_path / "world-home"))
    repo = tmp_path / "repo"
    worktree = tmp_path / "run" / "worktree"
    repo.mkdir()
    worktree.mkdir(parents=True)
    (repo / "README.md").write_text("# Registered\n", encoding="utf-8")
    (worktree / "README.md").write_text("# Worktree\n", encoding="utf-8")
    project = {
        "repo": str(repo),
        "stack": ["python"],
        "test_commands": [],
        "forbidden_paths": [],
        "world": {"write_policy": "zero_write"},
    }

    payload = ensure_project_memory(
        "demo",
        project,
        source_path=worktree,
        source_kind="worktree",
        source_ref="t_1",
    )

    memory = payload["memory"]
    assert memory["repo_path"] == str(repo.resolve())
    assert memory["source_kind"] == "worktree"
    assert memory["source_path"] == str(worktree.resolve())
    assert memory["source_ref"] == "t_1"
    assert "Worktree" in payload["prompt"]
    assert "Registered" not in payload["prompt"]
