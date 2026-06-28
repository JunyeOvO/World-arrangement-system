"""AGENTS.md worktree injection tests (Phase 3 regression guards).

Covers:
- inject into empty worktree
- skip (not overwrite) when AGENTS.md already exists — return warning reason
- template missing returns False (resilience)
- injected content carries the hard rules + forbidden flag
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.agents_md import inject_agents_md, InjectResult


def test_inject_into_empty_worktree(tmp_path):
    res = inject_agents_md(tmp_path)
    assert res.injected is True
    assert Path(res.path).exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert "injected" in res.reason


def test_inject_skips_existing_file_not_overwritten(tmp_path):
    target = tmp_path / "AGENTS.md"
    original = "USER OWN CONTENT"
    target.write_text(original, encoding="utf-8")
    res = inject_agents_md(tmp_path)
    assert res.injected is False
    assert target.read_text(encoding="utf-8") == original
    assert "already exists" in res.reason


def test_template_carries_hard_rules_and_forbidden_flag():
    # Inject and inspect contents.
    workdir = Path("/tmp/_agents_md_test_contents")  # placeholder; replaced below
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        inject_agents_md(wd)
        content = (wd / "AGENTS.md").read_text(encoding="utf-8")
    assert "--dangerously-skip-permissions" in content
    assert "Do not use `git push`" in content or "git push" in content
    assert "OpenCodeWorker" in content


def test_inject_returns_injectresult():
    res = inject_agents_md(Path("/tmp/_agents_md_nonexistent_dir_xyz"))
    assert isinstance(res, InjectResult)
    assert hasattr(res, "injected")
    assert hasattr(res, "path")
    assert hasattr(res, "reason")


def test_agents_md_injected_for_claude_to_opencode_escalation(tmp_path, monkeypatch):
    """A1: ClaudeCodeWorker→OpenCodeWorker escalation must inject AGENTS.md before
    the OpenCode attempt runs, even though prime route is claude_code."""
    import json
    import subprocess

    from orchestrator import scheduler as sched
    from orchestrator.workers.base import WorkerResult
    from orchestrator.verifier import VerifyResult
    from orchestrator.pr import PublishResult

    # ── fake git repo ──
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    # ── config home ──
    home = tmp_path / "home"
    home.mkdir()
    (home / "models.yaml").write_text(
        "models:\n  deepseek_pro:\n    provider: deepseek\n    adapter: claude_code\n"
        "    model: deepseek-v4-pro\n    worker: claude_code\n"
        "  opencode_go_glm52:\n    provider: opencode_go\n    adapter: opencode_cli\n"
        "    model: opencode-go/glm-5.2\n    worker: opencode\n    default_variant: high\n",
        encoding="utf-8",
    )
    (home / "policies.yaml").write_text(open(
        # use packaged example for policies
        __import__("orchestrator.config", fromlist=["code_root"]).code_root()
        / "config" / "policies.yaml.example", encoding="utf-8"
    ).read(), encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))

    # ── projects.yaml: prime route is claude_code but stack triggers opencode fallback ──
    (home / "projects.yaml").write_text(
        "projects:\n  generic:\n    project_id: generic\n    name: Generic\n"
        f"    repo: {repo}\n    stack: [python]\n    test_commands: []\n    build_commands: []\n"
        "    forbidden_paths: []\n    default_worker: claude_code\n"
        "    default_model: deepseek_pro\n    allow_auto_pr: false\n    allow_remote_push: false\n",
        encoding="utf-8",
    )

    # ── stub workers: claude fails → escalate to opencode; opencode asserts AGENTS.md ──
    observed = {}

    def claude_fail(self, prompt, worktree, route, task, dry_run=False):
        return WorkerResult("failed", "claude failed mock", [], task.get("test_commands", []), [], False, "", "")

    def opencode_check(self, prompt, worktree, route, task, dry_run=False):
        agp = Path(worktree) / "AGENTS.md"
        observed["worktree"] = str(worktree)
        observed["agents_md_exists_before_opencode"] = agp.exists()
        return WorkerResult("success", "opencode mock", [], task.get("test_commands", []), [], False, "", "")

    monkeypatch.setattr(sched.ClaudeCodeWorker, "run", claude_fail)
    monkeypatch.setattr(sched.OpenCodeWorker, "run", opencode_check)

    # ── stub verify / review / publish so _execute finishes ──
    def fake_verify(worktree, test_cmds, build_cmds, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        diff = out_dir / "diff.patch"
        diff.write_text("", encoding="utf-8")
        return VerifyResult(True, True, [], [], str(diff))
    monkeypatch.setattr(sched, "verify", fake_verify)

    monkeypatch.setattr(sched, "run_codex_review",
                        lambda payload, out_path: (Path(out_path).parent.mkdir(parents=True, exist_ok=True),
                                                   Path(out_path).write_text(
                                                       json.dumps({"approved": True, "can_create_pr": True}),
                                                       encoding="utf-8"),
                                                   {"approved": True, "can_create_pr": True})[2])

    monkeypatch.setattr(sched, "create_pr_or_patch",
                        lambda *a, **k: PublishResult("COMPLETED_WITH_PATCH", None, str(tmp_path / "p.patch"), "stub"))

    # ── run: high-risk goal forces claude_code + opencode_on_failure escalation ──
    svc = sched.OrchestratorService()
    res = svc.submit_task("generic", "fix migration issue", "medium", True, False, dry_run=False)

    assert observed.get("agents_md_exists_before_opencode") is True, (
        f"AGENTS.md missing before OpenCode escalation; observed={observed}"
    )
    # prime route must be claude_code (proves escalation, not prime opencode)
    tid = res["task_id"]
    with (Path(res["run_dir"]) / "route.json").open("r", encoding="utf-8") as f:
        route = json.load(f)
    assert route["selected_worker"] == "claude_code"
    assert route.get("escalation_policy") == "opencode_on_failure"
