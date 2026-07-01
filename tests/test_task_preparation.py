from pathlib import Path
from types import SimpleNamespace

from orchestrator.artifacts import ArtifactStore
from orchestrator.task_preparation import TaskPreparationService
from orchestrator.worktree import WorktreeInfo

PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lwH4NwAAAABJRU5ErkJggg=="


def _worktree_preparer(repo, base_branch, task_id, root, dry_run=False):
    path = root / "worktrees" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return WorktreeInfo(repo=repo, branch=f"ai/{task_id}", path=str(path), dry_run=dry_run)


class FakeVisionAdapter:
    def analyze(self, **kwargs):
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            to_dict=lambda: {
                "observations": ["image ok"],
                "confidence": 0.91,
                "degraded": False,
            }
        )


def _service(tmp_path: Path, statuses=None, agents_injector=None):
    statuses = statuses if statuses is not None else []
    return TaskPreparationService(
        artifacts=ArtifactStore(tmp_path / "runs"),
        set_status=lambda task_id, status, event, payload: statuses.append((status, event, payload)),
        worktree_preparer=_worktree_preparer,
        agents_injector=agents_injector or (lambda path: SimpleNamespace(injected=True, path=str(path / "AGENTS.md"))),
        vision_adapter_factory=lambda: FakeVisionAdapter(),
    )


def _task(tmp_path: Path) -> dict:
    run_dir = tmp_path / "runs" / "t_prepare"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "task_id": "t_prepare",
        "project_id": "demo",
        "run_dir": str(run_dir),
        "user_goal": "inspect",
    }


def test_preparation_creates_worktree_and_status(tmp_path: Path):
    statuses = []
    service = _service(tmp_path, statuses=statuses)
    task = _task(tmp_path)

    result = service.prepare(
        task_id="t_prepare",
        task=task,
        project={"repo": str(tmp_path / "repo"), "default_branch": "main"},
        route={"selected_worker": "claude_code"},
        dry_run=True,
    )

    assert Path(result.worktree.path).exists()
    assert task["worktree_path"] == result.worktree.path
    assert statuses[0] == ("WORKTREE_READY", "worktree_ready", result.worktree.__dict__)
    assert statuses[1][0:2] == ("WORKTREE_READY", "project_memory_refreshed")
    assert task["project_memory"]["memory"]["source_kind"] == "worktree"
    assert task["project_memory"]["memory"]["source_ref"] == "t_prepare"
    assert (tmp_path / "runs" / "t_prepare" / "worktree.json").exists()
    assert (tmp_path / "runs" / "t_prepare" / "task.json").exists()


def test_preparation_adds_vision_observation(tmp_path: Path):
    statuses = []
    service = _service(tmp_path, statuses=statuses)
    task = {**_task(tmp_path), "image_base64": [f"data:image/png;base64,{PNG_BASE64}"]}

    service.prepare(
        task_id="t_prepare",
        task=task,
        project={"repo": str(tmp_path / "repo")},
        route={"selected_worker": "claude_code"},
    )

    assert task["vision_observation"]["observations"] == ["image ok"]
    assert task["vision_observation_path"].endswith("multimodal\\vision_observation.json") or task["vision_observation_path"].endswith("multimodal/vision_observation.json")
    assert statuses[-1][0:2] == ("WORKTREE_READY", "vision_observation_ready")
    assert (tmp_path / "runs" / "t_prepare" / "task.json").exists()


def test_preparation_records_opencode_agents_skip(tmp_path: Path):
    statuses = []
    service = _service(
        tmp_path,
        statuses=statuses,
        agents_injector=lambda path: SimpleNamespace(injected=False, path=str(path / "AGENTS.md"), reason="exists"),
    )
    task = _task(tmp_path)

    service.prepare(
        task_id="t_prepare",
        task=task,
        project={"repo": str(tmp_path / "repo")},
        route={"selected_worker": "opencode"},
    )

    assert statuses[-1][0:2] == ("WORKTREE_READY", "agents_md_skipped")
    assert (tmp_path / "runs" / "t_prepare" / "agents_md.json").exists()
