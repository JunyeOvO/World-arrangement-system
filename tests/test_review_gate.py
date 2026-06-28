import json
import subprocess
from pathlib import Path

from orchestrator.reviewer import run_codex_review
from orchestrator.scheduler import OrchestratorService


def test_low_risk_codex_unavailable_uses_degraded_local_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("orchestrator.reviewer.shutil.which", lambda name: None)

    review = run_codex_review(
        {"risk_level": "low", "tests_passed": True, "forbidden_paths_touched": False},
        tmp_path / "review.json",
    )

    assert review["approved"] is True
    assert review["review_mode"] == "local_fallback"
    assert review["degraded"] is True
    assert review["degradation_reason"] == "codex CLI not found"
    assert review["can_create_pr"] is True


def test_medium_risk_codex_unavailable_is_degraded_not_approved(tmp_path, monkeypatch):
    monkeypatch.setattr("orchestrator.reviewer.shutil.which", lambda name: None)

    review = run_codex_review(
        {"risk_level": "medium", "tests_passed": True, "forbidden_paths_touched": False},
        tmp_path / "review.json",
    )

    assert review["approved"] is False
    assert review["review_mode"] == "local_fallback"
    assert review["degraded"] is True
    assert review["can_create_pr"] is False
    assert "Codex review must be available" in review["required_changes"][-1]


def test_codex_available_uses_codex_review_mode(tmp_path, monkeypatch):
    class Proc:
        stdout = json.dumps(
            {
                "approved": True,
                "risk_level": "medium",
                "blocking_issues": [],
                "non_blocking_issues": [],
                "required_changes": [],
                "final_recommendation": "create PR",
                "can_create_pr": True,
            }
        )
        returncode = 0

    monkeypatch.setattr("orchestrator.reviewer.shutil.which", lambda name: "codex")
    monkeypatch.setattr("orchestrator.reviewer.subprocess.run", lambda *args, **kwargs: Proc())

    review = run_codex_review(
        {"risk_level": "medium", "tests_passed": True, "forbidden_paths_touched": False},
        tmp_path / "review.json",
    )

    assert review["approved"] is True
    assert review["review_mode"] == "codex"
    assert review["degraded"] is False
    assert review["can_create_pr"] is True


def test_scheduler_medium_degraded_review_needs_user_not_publish(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    home = tmp_path / "home"
    home.mkdir()
    (home / "models.yaml").write_text(
        "models:\n  deepseek_pro:\n    provider: deepseek\n    adapter: claude_code\n"
        "    model: deepseek-v4-pro\n    worker: claude_code\n",
        encoding="utf-8",
    )
    (home / "policies.yaml").write_text(
        Path("config/policies.yaml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (home / "projects.yaml").write_text(
        "projects:\n  generic:\n    project_id: generic\n    name: Generic\n"
        f"    repo: {repo}\n    stack: [python]\n    test_commands: []\n    build_commands: []\n"
        "    forbidden_paths: []\n    default_worker: claude_code\n"
        "    default_model: deepseek_pro\n    allow_auto_pr: false\n    allow_remote_push: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    monkeypatch.setattr("orchestrator.scheduler._task_requires_diff", lambda task: False)
    monkeypatch.setattr("orchestrator.scheduler.run_codex_review", lambda inputs, output_path: (
        Path(output_path).parent.mkdir(parents=True, exist_ok=True),
        Path(output_path).write_text(json.dumps({
            "approved": False,
            "review_mode": "local_fallback",
            "degraded": True,
            "degradation_reason": "codex CLI not found",
            "available": False,
            "can_create_pr": False,
            "blocking_issues": [],
            "non_blocking_issues": ["codex CLI not found"],
            "required_changes": ["Codex review must be available for medium+ risk tasks"],
        }), encoding="utf-8"),
        json.loads(Path(output_path).read_text(encoding="utf-8")),
    )[2])

    service = OrchestratorService()
    result = service.submit_task("generic", "analyze repository", "medium", True, False, dry_run=True)
    status = service.get_task_status(result["task_id"])
    final_md = (Path(result["run_dir"]) / "final.md").read_text(encoding="utf-8")

    assert status["status"] == "NEEDS_USER"
    assert any(event["event_type"] == "review_degraded_needs_user" for event in status["events"])
    assert "Mode: local_fallback" in final_md
    assert "Degraded: True" in final_md
    assert not (Path(result["run_dir"]) / "publish.json").exists()
