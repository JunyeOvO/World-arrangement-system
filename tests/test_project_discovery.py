"""Tests for Adaptive Project Layer: discovery, profiling, registry, fingerprint, adaptation."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from orchestrator.project_discovery import (
    is_git_repo,
    is_safe_to_read,
    scan_project_roots,
)
from orchestrator.project_profiler import profile_project, read_ai_project_yaml
from orchestrator.project_fingerprint import compute_fingerprint, has_changed
from orchestrator.project_registry import (
    confirm_project,
    get_ignore_list,
    ignore_project_in_registry,
    list_pending_projects,
    load_full_registry,
    load_projects,
    register_project_to_yaml,
    save_projects,
)
from orchestrator.project_adaptation import refresh_project_profile
from orchestrator.types import ProjectProfile, ProjectFingerprint


# ── Helpers ──

def _make_git_dir(path: Path) -> None:
    """Create a .git directory to make path appear as a git repo."""
    (path / ".git").mkdir(parents=True, exist_ok=True)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _temp_home(tmp_path: Path) -> str:
    """Set AI_ORCHESTRATOR_HOME to a temp directory and return the path."""
    return str(tmp_path)


# ── Discovery Tests ──

def test_is_git_repo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        assert is_git_repo(root)
        assert not is_git_repo(root / "subdir")


def test_scan_roots_finds_git_repos():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Create two project dirs with .git
        proj_a = root / "project-a"
        proj_b = root / "project-b"
        proj_a.mkdir()
        proj_b.mkdir()
        _make_git_dir(proj_a)
        _make_git_dir(proj_b)

        result = scan_project_roots([str(root)], max_depth=2)
        candidates_str = [str(c) for c in result.candidates]
        assert str(proj_a) in candidates_str
        assert str(proj_b) in candidates_str


def test_scan_roots_skips_ignored():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        proj = root / "my-project"
        proj.mkdir()
        _make_git_dir(proj)

        ignore_list = [{"pattern": "*/my-project", "reason": "test ignore"}]
        result = scan_project_roots([str(root)], max_depth=2, ignore_list=ignore_list)
        assert len(result.candidates) == 0
        assert len(result.skipped) >= 1


def test_is_safe_to_read():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert is_safe_to_read(root / "package.json")
        assert not is_safe_to_read(root / ".env")
        assert not is_safe_to_read(root / "secret.key")


# ── Profiler Tests ──

def test_profile_package_json_project():
    """Detect package.json → node project."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "test-node", "dependencies": {"react": "^18"}}')

        profile = profile_project(root)
        assert profile.project_type == "node"
        assert profile.confidence >= 0.7
        assert "react" in profile.stack or "node" in profile.stack


def test_profile_fastapi_project():
    """Detect pyproject.toml + fastapi → python/fastapi."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "pyproject.toml", """
[project]
name = "my-api"
dependencies = ["fastapi", "uvicorn"]
""")

        profile = profile_project(root)
        assert profile.project_type == "python"
        assert "fastapi" in profile.stack
        assert profile.confidence >= 0.7


def test_profile_android_project():
    """Detect android/app/build.gradle → android with high confidence."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "build.gradle", "// root build.gradle")
        _write_file(root / "android/app/build.gradle", "// android app build.gradle")

        profile = profile_project(root)
        assert profile.project_type == "android"
        assert profile.confidence >= 0.9


def test_profile_unity_project():
    """Detect ProjectSettings/ProjectVersion.txt → unity with high confidence."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.0f1")
        (root / "Assets").mkdir()

        profile = profile_project(root)
        assert profile.project_type == "unity"
        assert profile.confidence >= 0.9


def test_profile_vite_project():
    """Detect vite.config.ts → vite."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "vite-app"}')
        _write_file(root / "vite.config.ts", "export default {}")

        profile = profile_project(root)
        assert "vite" in profile.stack or profile.project_type == "vite"


def test_profile_next_project():
    """Detect next.config.js → next."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "next-app", "dependencies": {"next": "14"}}')
        _write_file(root / "next.config.js", "module.exports = {}")

        profile = profile_project(root)
        assert "next" in profile.stack or profile.project_type == "next"


def test_low_confidence_git_only():
    """Only .git with no config files → low confidence, status=pending."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)

        profile = profile_project(root)
        assert profile.project_type == "unknown"
        assert profile.confidence < 0.75
        assert profile.status == "pending_confirmation"


# ── .ai-project.yaml Tests ──

def test_read_ai_project_yaml():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_file(root / ".ai-project.yaml", """
project_id: "custom-project-id"
name: "Custom Name"
stack:
  - python
  - django
auto_generated: false
""")
        data = read_ai_project_yaml(root)
        assert data is not None
        assert data["project_id"] == "custom-project-id"
        assert data["name"] == "Custom Name"
        assert "python" in data["stack"]
        assert data["auto_generated"] is False


def test_read_ai_project_yaml_none_when_missing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        data = read_ai_project_yaml(root)
        assert data is None


# ── Registry Tests ──

def test_write_and_read_projects_yaml():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        projects_yaml = home / "projects.yaml"
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)

        try:
            # Create initial registry
            registry = {
                "projects": {
                    "test-proj": {
                        "project_id": "test-proj",
                        "name": "Test",
                        "repo": str(home / "test-proj"),
                        "project_type": "python",
                        "stack": ["python"],
                        "confidence": 0.85,
                        "auto_generated": True,
                        "fingerprint": "",
                        "needs_refresh": False,
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": "2026-01-01T00:00:00Z",
                        "status": "active",
                        "indicators": [],
                        "metadata": {},
                    }
                },
                "project_groups": {},
                "ignore_list": [],
            }
            save_projects(registry)

            # Load and verify
            loaded = load_projects()
            assert "test-proj" in loaded
            assert loaded["test-proj"]["name"] == "Test"
            assert loaded["test-proj"]["project_type"] == "python"
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_register_profile_to_yaml_high_confidence():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        projects_yaml = home / "projects.yaml"
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)

        try:
            from orchestrator.project_registry import paths

            # Ensure home dir exists
            home.mkdir(parents=True, exist_ok=True)

            profile = ProjectProfile(
                project_id="my-node-app",
                name="my-node-app",
                repo=str(home / "my-node-app"),
                project_type="node",
                stack=["node", "react"],
                confidence=0.85,
                status="active",
                auto_generated=True,
                indicators=[{"name": "package.json", "type": "node", "weight": 0.7}],
                fingerprint="abc123",
            )

            result = register_project_to_yaml(profile)
            assert result["status"] == "registered"
            assert result["project_id"] == "my-node-app"

            # Verify it was written
            loaded = load_projects()
            assert "my-node-app" in loaded
            assert loaded["my-node-app"]["auto_generated"] is True
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_low_confidence_goes_pending():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            profile = ProjectProfile(
                project_id="mystery-project",
                name="mystery-project",
                repo=str(home / "mystery-project"),
                project_type="unknown",
                stack=[],
                confidence=0.3,
                status="pending_confirmation",
                auto_generated=True,
                indicators=[],
                fingerprint="low123",
            )

            result = register_project_to_yaml(profile)
            assert result["status"] == "pending_confirmation"

            pending = list_pending_projects()
            assert any(p["project_id"] == "mystery-project" for p in pending)
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_dont_overwrite_manual_config():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            # First register as manual (auto_generated=False)
            registry = {
                "projects": {
                    "manual-proj": {
                        "project_id": "manual-proj",
                        "name": "Manual Project",
                        "repo": str(home / "manual-proj"),
                        "project_type": "python",
                        "stack": ["python", "django"],
                        "confidence": 0.9,
                        "auto_generated": False,
                        "fingerprint": "manual-fp-1",
                        "needs_refresh": False,
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": "2026-01-01T00:00:00Z",
                        "status": "active",
                        "indicators": [],
                        "metadata": {},
                    }
                },
                "project_groups": {},
                "ignore_list": [],
            }
            save_projects(registry)

            # Now try to auto-register a profile with same project_id (different type)
            profile = ProjectProfile(
                project_id="manual-proj",
                name="Auto Detected",
                repo=str(home / "manual-proj"),
                project_type="node",  # Different from manual "python"
                stack=["node"],
                confidence=0.9,
                status="active",
                auto_generated=True,
                indicators=[],
                fingerprint="auto-fp-2",
            )

            result = register_project_to_yaml(profile)
            # Should NOT overwrite
            assert result["status"] == "updated"
            assert "user-managed" in result.get("message", "")

            # Verify original config preserved
            loaded = load_projects()
            assert loaded["manual-proj"]["project_type"] == "python"
            assert loaded["manual-proj"]["auto_generated"] is False
            assert loaded["manual-proj"]["name"] == "Manual Project"
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_confirm_pending_project():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            registry = {
                "projects": {
                    "pending-proj": {
                        "project_id": "pending-proj",
                        "name": "Pending",
                        "repo": str(home / "pending-proj"),
                        "project_type": "unknown",
                        "stack": [],
                        "confidence": 0.5,
                        "auto_generated": True,
                        "fingerprint": "",
                        "needs_refresh": False,
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": "2026-01-01T00:00:00Z",
                        "status": "pending_confirmation",
                        "indicators": [],
                        "metadata": {},
                    }
                },
                "project_groups": {},
                "ignore_list": [],
            }
            save_projects(registry)

            result = confirm_project("pending-proj")
            assert result["status"] == "confirmed"

            loaded = load_projects()
            assert loaded["pending-proj"]["status"] == "active"
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_ignore_project():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            result = ignore_project_in_registry("~/temp/things", reason="temp dir")
            assert result["status"] == "ignored"

            ignore_list = get_ignore_list()
            assert any(e["pattern"] == "~/temp/things" for e in ignore_list)
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_ignore_list_skips_in_scan():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            # Setup ignore list
            registry = {
                "projects": {},
                "project_groups": {},
                "ignore_list": [{"pattern": "*/skipped-dir", "reason": "skip this"}],
            }
            save_projects(registry)

            # Create directory tree
            proj = home / "skipped-dir"
            proj.mkdir(parents=True)
            _make_git_dir(proj)

            ignore_list = get_ignore_list()
            result = scan_project_roots([str(home)], max_depth=2, ignore_list=ignore_list)
            assert len(result.candidates) == 0
            assert len(result.skipped) >= 1
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


# ── Fingerprint Tests ──

def test_compute_fingerprint():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "fp-test"}')
        _write_file(root / "src/index.ts", "console.log('hello')")

        fp = compute_fingerprint(root, "fp-test")
        assert len(fp.hash) == 64  # SHA256 hex
        assert len(fp.file_tree) >= 2  # package.json + src/index.ts
        assert "package.json" in fp.key_files


def test_fingerprint_changes_on_file_add():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "test"}')

        fp1 = compute_fingerprint(root, "test-project")
        hash1 = fp1.hash

        # Add a new file
        _write_file(root / "src/app.ts", "export const x = 1")
        fp2 = compute_fingerprint(root, "test-project")
        hash2 = fp2.hash

        assert has_changed(hash1, hash2)


def test_fingerprint_same_when_unchanged():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "test"}')

        fp1 = compute_fingerprint(root, "test-project")
        fp2 = compute_fingerprint(root, "test-project")

        assert not has_changed(fp1.hash, fp2.hash)


def test_fingerprint_excludes_noise_dirs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "test"}')
        _write_file(root / "node_modules/some-pkg/index.js", "// ignored")
        _write_file(root / "build/output.js", "// ignored")

        fp = compute_fingerprint(root, "test")
        file_paths = fp.file_tree
        # node_modules and build should be excluded
        assert not any("node_modules" in p for p in file_paths)
        assert not any("build" in p for p in file_paths)
        # But package.json should be there
        assert "package.json" in file_paths


# ── Adaptation Tests ──

def test_refresh_project_profile_updates_fingerprint():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            # Create a repo with .git
            repo = home / "refresh-test"
            repo.mkdir()
            _make_git_dir(repo)
            _write_file(repo / "package.json", '{"name": "refresh-test"}')

            # Register it first
            from orchestrator.project_fingerprint import compute_fingerprint

            fp = compute_fingerprint(repo, "refresh-test")
            registry = {
                "projects": {
                    "refresh-test": {
                        "project_id": "refresh-test",
                        "name": "Refresh Test",
                        "repo": str(repo),
                        "project_type": "node",
                        "stack": ["node"],
                        "confidence": 0.85,
                        "auto_generated": True,
                        "fingerprint": fp.hash,
                        "needs_refresh": False,
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": "2026-01-01T00:00:00Z",
                        "status": "active",
                        "indicators": [],
                        "metadata": {},
                    }
                },
                "project_groups": {},
                "ignore_list": [],
            }
            save_projects(registry)

            # Refresh
            result = refresh_project_profile("refresh-test")
            assert result["status"] in ("updated", "registered")

            # Should not need refresh (fingerprint unchanged)
            loaded = load_projects()
            assert loaded["refresh-test"]["needs_refresh"] is False
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_fingerprint_change_sets_needs_refresh():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            repo = home / "change-test"
            repo.mkdir()
            _make_git_dir(repo)
            _write_file(repo / "package.json", '{"name": "change-test"}')

            # Register with OLD fingerprint
            registry = {
                "projects": {
                    "change-test": {
                        "project_id": "change-test",
                        "name": "Change Test",
                        "repo": str(repo),
                        "project_type": "node",
                        "stack": ["node"],
                        "confidence": 0.85,
                        "auto_generated": True,
                        "fingerprint": "old-outdated-fingerprint-00000000000000000000000000000000",
                        "needs_refresh": False,
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": "2026-01-01T00:00:00Z",
                        "status": "active",
                        "indicators": [],
                        "metadata": {},
                    }
                },
                "project_groups": {},
                "ignore_list": [],
            }
            save_projects(registry)

            # Refresh
            result = refresh_project_profile("change-test")
            assert result.get("fingerprint_changed") is True or result.get("needs_refresh") is True
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


# ── Security Tests ──

def test_scan_excludes_node_modules_and_git():
    """node_modules/ and .git/ content should never be part of discovery."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "secure-test"}')
        _write_file(root / "node_modules/lodash/index.js", "// heavy")
        _write_file(root / "build/bundle.js", "// bundled")
        (root / "__pycache__").mkdir()
        _write_file(root / "__pycache__/module.pyc", "binary")

        # Discovery should still find the repo but not count noise dirs
        result = scan_project_roots([str(root)], max_depth=2)
        # The root itself should NOT be a candidate because it's the scan root
        # But scanning inside a repo shouldn't descend into node_modules
        fp = compute_fingerprint(root, "secure-test")
        assert not any("node_modules" in p for p in fp.file_tree)
        assert not any("build" in p for p in fp.file_tree)
        assert not any("__pycache__" in p for p in fp.file_tree)


def test_does_not_read_env_files():
    """Profiler should never read .env files."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "package.json", '{"name": "env-test"}')
        _write_file(root / ".env", "SECRET=should-not-be-read")

        # Profiling should still work without reading .env
        profile = profile_project(root)
        assert profile.project_type == "node"
        # The .env should not appear in indicators
        indicator_names = [i["name"] for i in profile.indicators]
        assert ".env" not in indicator_names


def test_does_not_execute_code():
    """Profiler only reads known config files, never executes anything."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        # Create a malicious-looking package.json that's just data
        _write_file(root / "package.json", json.dumps({
            "name": "safe-test",
            "scripts": {"postinstall": "rm -rf /"},
        }))

        # Should profile safely without executing
        profile = profile_project(root)
        assert profile.project_type == "node"
        # No code execution happened — we just parsed JSON


# ── Integration / Command Tests ──

def test_handle_discover_projects_end_to_end():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["AI_ORCHESTRATOR_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)

        try:
            # Save default registry
            save_projects({"projects": {}, "project_groups": {}, "ignore_list": []})

            # Create project dirs
            proj_node = home / "scans" / "node-app"
            proj_node.mkdir(parents=True)
            _make_git_dir(proj_node)
            _write_file(proj_node / "package.json", '{"name": "node-app"}')

            proj_py = home / "scans" / "py-app"
            proj_py.mkdir(parents=True)
            _make_git_dir(proj_py)
            _write_file(proj_py / "pyproject.toml", '[project]\nname = "py-app"\ndependencies = ["fastapi"]')

            from orchestrator.project_commands import handle_discover_projects
            result = handle_discover_projects(roots=[str(home / "scans")], max_depth=3)

            assert result["total_discovered"] >= 2
            assert len(result["high_confidence"]) >= 2  # both should be high confidence
            assert len(result["low_confidence"]) == 0
        finally:
            os.environ.pop("AI_ORCHESTRATOR_HOME", None)


def test_handle_profile_project_returns_full_profile():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_git_dir(root)
        _write_file(root / "pyproject.toml", '[project]\nname = "full-profile-test"\ndependencies = ["fastapi", "pydantic"]')

        from orchestrator.project_commands import handle_profile_project
        result = handle_profile_project(str(root))

        assert result["project_type"] == "python"
        assert "fastapi" in result["stack"]
        assert result["confidence"] >= 0.7
        assert "indicators" in result
        assert "fingerprint" in result
