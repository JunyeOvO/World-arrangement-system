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
    assert second["memory"]["stats"]["hit_count"] >= 1
    assert "## Project Memory" in second["prompt"]
