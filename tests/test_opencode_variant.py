"""Variant routing tests for OpenCodeWorker / Route (Phase 4 regression guards).

Covers:
- _normalize_variant: None/""/default -> omit; high/max/minimal -> pass; bogus -> downgrade+warn
- Route.variant populated by router for GLM-5.2 / complex / hard_bugfix
- Route.to_dict carries variant
- model key alias resolves opencode-go/glm-5.2 to opencode_go_glm52 spec
"""
from __future__ import annotations

import pytest

from orchestrator.router import plan_route
from orchestrator.workers.opencode_worker import _normalize_variant
from orchestrator.env_profiles import model_spec


# ── _normalize_variant ──

@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("", None),
    ("default", None),
    ("Default", None),   # case-insensitive
    ("high", "high"),
    ("max", "max"),
    ("minimal", "minimal"),
])
def test_normalize_variant_valid(raw, expected):
    cli, warn = _normalize_variant(raw)
    assert cli == expected
    assert warn is None


def test_normalize_variant_unknown_downgrades_with_warning():
    cli, warn = _normalize_variant("bogus")
    assert cli is None
    assert warn is not None
    assert "bogus" in warn
    assert "high" in warn or "max" in warn or "minimal" in warn


# ── Route.variant populated ──

def test_route_explicit_glm52_variant_high():
    r = plan_route({"user_goal": "用 GLM-5.2 修 bug", "risk_level": "medium"}, {})
    assert r.selected_worker == "opencode"
    assert r.selected_model == "opencode-go/glm-5.2"
    assert r.variant == "high"


def _opencode_attempts(route):
    return [a for a in (route.to_dict().get("retry_chain") or []) if a.get("worker") == "opencode"]


def test_route_complex_coding_escalates_to_opencode_high():
    """V2: complex_coding primes Claude (save quota) and escalates to OpenCode high→max."""
    r = plan_route({"user_goal": "refactor data layer", "risk_level": "medium",
                    "task_type": "complex_coding"}, {})
    oc = _opencode_attempts(r)
    assert oc, "retry chain must contain an OpenCode escalation for complex tasks"
    variants = [a.get("variant") for a in oc]
    assert "high" in variants  # first escalation per spec §6


def test_route_hard_bugfix_variant_max():
    r = plan_route({"user_goal": "fix race crash", "risk_level": "high",
                    "task_type": "hard_bugfix"}, {})
    assert r.variant == "max"


@pytest.mark.parametrize("tt", ["large_refactor", "large_context"])
def test_route_large_task_escalates_to_opencode_high(tt):
    """V2: large tasks prime Claude and escalate to OpenCode high→max."""
    r = plan_route({"user_goal": "understand large code", "risk_level": "medium",
                    "task_type": tt}, {})
    oc = _opencode_attempts(r)
    assert oc, "retry chain must contain an OpenCode escalation for large tasks"
    variants = [a.get("variant") for a in oc]
    assert "high" in variants


def test_route_non_opencode_variant_none():
    # default docs route -> claude_code, variant must be None
    r = plan_route({"user_goal": "更新 README 文档", "risk_level": "low"}, {})
    assert r.selected_worker == "claude_code"
    assert r.variant is None


def test_route_to_dict_carries_variant():
    r = plan_route({"user_goal": "用 GLM-5.2 修 bug", "risk_level": "medium"}, {})
    d = r.to_dict()
    assert "variant" in d
    assert d["variant"] == "high"


# ── model key alias (A3: fixture-based, no false-green {} == {}) ──

def test_model_spec_alias_resolves_glm52(tmp_path, monkeypatch):
    """A3: alias test must use a real models.yaml fixture and assert non-empty spec."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "models.yaml").write_text(
        "models:\n"
        "  opencode_go_glm52:\n"
        "    provider: opencode_go\n"
        "    adapter: opencode_cli\n"
        "    model: opencode-go/glm-5.2\n"
        "    worker: opencode\n"
        "    default_variant: high\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))

    spec_by_key = model_spec("opencode_go_glm52")
    spec_by_model = model_spec("opencode-go/glm-5.2")

    # Must NOT be empty dict (the old false-green)
    assert spec_by_key != {}, "direct key lookup returned empty — alias test is meaningless"
    assert spec_by_model != {}, "alias lookup returned empty — alias not working"
    # Both keys resolve to the same spec
    assert spec_by_key == spec_by_model
    # Verify actual fields
    assert spec_by_model["model"] == "opencode-go/glm-5.2"
    assert spec_by_model["default_variant"] == "high"


# ── A2: project.default_variant as fallback ──

def _proj_opencode(variant):
    return {
        "project_id": "shiwu",
        "stack": ["android", "kotlin", "fastapi"],
        "default_worker": "opencode",
        "default_model": "opencode-go/glm-5.2",
        "default_variant": variant,
    }


def test_project_default_variant_max_is_used_when_no_strong_route_variant():
    p = _proj_opencode("max")
    r = plan_route({"user_goal": "add a small log line", "risk_level": "low",
                    "task_type": "routine_coding"}, p)
    assert r.selected_worker == "opencode"
    assert r.variant == "max"


def test_project_default_variant_default_maps_to_none():
    p = _proj_opencode("default")
    r = plan_route({"user_goal": "add a small log line", "risk_level": "low",
                    "task_type": "routine_coding"}, p)
    assert r.selected_worker == "opencode"
    assert r.variant is None


def test_project_default_variant_none_maps_to_none():
    p = _proj_opencode(None)
    r = plan_route({"user_goal": "add a small log line", "risk_level": "low",
                    "task_type": "routine_coding"}, p)
    assert r.selected_worker == "opencode"
    assert r.variant is None


def test_project_default_variant_unknown_maps_to_none():
    p = _proj_opencode("bogus")
    r = plan_route({"user_goal": "add a small log line", "risk_level": "low",
                    "task_type": "routine_coding"}, p)
    assert r.selected_worker == "opencode"
    # unknown variants must never reach the CLI — normalized to None
    assert r.variant is None


def test_explicit_glm52_overrides_project_default_variant():
    p = _proj_opencode("default")
    r = plan_route({"user_goal": "用 GLM-5.2 修 bug", "risk_level": "medium"}, p)
    assert r.selected_worker == "opencode"
    assert r.variant == "high"  # strong rule beats project default


def test_hard_bugfix_overrides_project_default_variant():
    p = _proj_opencode("default")
    r = plan_route({"user_goal": "fix race crash", "risk_level": "high",
                    "task_type": "hard_bugfix"}, p)
    assert r.selected_worker == "opencode"
    assert r.variant == "max"  # strong rule beats project default


# ── opencode worker dry-run honors variant via route (smoke) ──

def test_opencode_worker_dry_run_with_high_variant(tmp_path):
    """Dry-run must succeed and not depend on a real opencode CLI."""
    from orchestrator.workers.opencode_worker import OpenCodeWorker
    worker = OpenCodeWorker()
    route = {"selected_model": "opencode-go/glm-5.2", "selected_worker": "opencode",
             "variant": "high"}
    task = {"run_dir": str(tmp_path), "task_id": "t_v", "test_commands": [], "build_commands": []}
    res = worker.run("use GLM-5.2", tmp_path, route, task, dry_run=True)
    assert res.status == "success"


# ── A4: post-construction variant guard ──

from orchestrator.workers.opencode_worker import assert_valid_opencode_args


def test_opencode_variant_high_is_passed():
    args = ["opencode", "run", "-m", "opencode-go/glm-5.2", "--variant", "high",
            "--format", "json", "--dir", "/tmp/w", "--title", "t", "P"]
    assert_valid_opencode_args(args)  # no raise


def test_opencode_variant_max_is_passed():
    args = ["opencode", "run", "--variant", "max", "-m", "x", "P"]
    assert_valid_opencode_args(args)


def test_opencode_variant_minimal_is_passed():
    args = ["opencode", "run", "--variant", "minimal", "P"]
    assert_valid_opencode_args(args)


def test_opencode_variant_default_is_omitted():
    # When normalized to None, --variant must be entirely absent.
    # Simulate the args the worker builds for variant=None (no --variant token).
    args = ["opencode", "run", "-m", "opencode-go/glm-5.2", "--format", "json",
            "--dir", "/tmp/w", "--title", "t", "P"]
    assert_valid_opencode_args(args)  # no --variant at all -> OK
    assert "--variant" not in args


def test_opencode_variant_invalid_is_not_passed():
    # If someone bypasses normalization and inserts --variant bogus, guard raises.
    import pytest as _pytest
    with _pytest.raises(ValueError):
        assert_valid_opencode_args(["opencode", "run", "--variant", "bogus", "P"])


def test_opencode_command_never_contains_variant_default():
    """The literal `--variant default` must never appear in constructed args."""
    import pytest as _pytest
    with _pytest.raises(ValueError):
        assert_valid_opencode_args(["opencode", "run", "--variant", "default", "P"])
    # Also: a missing value after --variant must raise.
    with _pytest.raises(ValueError):
        assert_valid_opencode_args(["opencode", "run", "--variant"])


def test_opencode_wsl_dir_path_is_converted():
    from pathlib import Path
    from orchestrator.workers.opencode_worker import _path_for_cli

    converted = _path_for_cli(
        Path(r"C:\Users\fujunye\.ai-orchestrator\runs\t1\worktrees\t1"),
        "wsl -e opencode",
    )

    assert converted == "/mnt/c/Users/fujunye/.ai-orchestrator/runs/t1/worktrees/t1"
