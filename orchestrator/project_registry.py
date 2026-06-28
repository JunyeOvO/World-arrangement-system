from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import load_yaml, paths
from .types import ProjectProfile


@dataclass(frozen=True)
class ProjectMatch:
    project_id: str | None
    confidence: float
    matched_by: str
    needs_user: bool
    project: dict[str, Any] | None = None


def load_projects() -> dict[str, dict[str, Any]]:
    p = paths()
    if not p.projects_yaml.exists():
        fallback = p.code_root / "config" / "projects.yaml.example"
        data = load_yaml(fallback, {"projects": {}})
    else:
        data = load_yaml(p.projects_yaml, {"projects": {}})
    projects: dict[str, dict[str, Any]] = {}
    for project_id, project in data.get("projects", {}).items():
        value = dict(project or {})
        value.setdefault("project_id", project_id)
        projects[project_id] = value
    return projects


def load_full_registry() -> dict[str, Any]:
    """Load the complete projects.yaml including groups and ignore_list."""
    p = paths()
    if not p.projects_yaml.exists():
        fallback = p.code_root / "config" / "projects.yaml.example"
        data = load_yaml(fallback, {"projects": {}, "project_groups": {}, "ignore_list": []})
        return data
    data = load_yaml(p.projects_yaml, {"projects": {}, "project_groups": {}, "ignore_list": []})
    # Ensure all expected keys exist
    data.setdefault("projects", {})
    data.setdefault("project_groups", {})
    data.setdefault("ignore_list", [])
    return data


def save_projects(registry: dict[str, Any]) -> None:
    """Save the full registry to ~/.ai-orchestrator/projects.yaml."""
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    with open(p.projects_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(registry, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def register_project_to_yaml(profile: ProjectProfile, force: bool = False) -> dict[str, Any]:
    """Register or update a project in projects.yaml. Returns status dict."""
    registry = load_full_registry()
    projects = registry.setdefault("projects", {})

    existing = projects.get(profile.project_id)

    if existing and not existing.get("auto_generated", True) and not force:
        # User-managed project: only update last_seen and fingerprint
        existing["last_seen"] = profile.last_seen
        existing["fingerprint"] = profile.fingerprint
        if profile.fingerprint and existing.get("fingerprint") and profile.fingerprint != existing["fingerprint"]:
            existing["needs_refresh"] = True
        save_projects(registry)
        return {"status": "updated", "project_id": profile.project_id, "message": "user-managed, fingerprint updated only"}

    if profile.confidence < 0.75 and not force:
        # Low confidence: write as pending
        entry = _profile_to_dict(profile)
        entry["status"] = "pending_confirmation"
        projects[profile.project_id] = entry
        save_projects(registry)
        return {"status": "pending_confirmation", "project_id": profile.project_id, "message": "low confidence, pending user confirmation"}

    # Auto-register or force
    entry = _profile_to_dict(profile)
    entry["status"] = "active"
    entry["auto_generated"] = True
    projects[profile.project_id] = entry
    save_projects(registry)
    return {"status": "registered", "project_id": profile.project_id, "message": "project registered"}


def confirm_project(project_id: str) -> dict[str, Any]:
    """Confirm a pending project and move it to active status."""
    registry = load_full_registry()
    projects = registry.get("projects", {})

    if project_id not in projects:
        return {"status": "not_found", "project_id": project_id, "message": "project not found in registry"}

    project = projects[project_id]
    if project.get("status") != "pending_confirmation":
        return {"status": "already_active", "project_id": project_id, "message": f"project is already {project.get('status')}"}

    project["status"] = "active"
    project["auto_generated"] = True
    project["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_projects(registry)
    return {"status": "confirmed", "project_id": project_id, "message": "project confirmed and activated"}


def ignore_project_in_registry(project_id_or_path: str, reason: str = "") -> dict[str, Any]:
    """Add a project to the ignore list in projects.yaml."""
    registry = load_full_registry()

    # First, check if it's a registered project
    projects = registry.get("projects", {})
    if project_id_or_path in projects:
        projects[project_id_or_path]["status"] = "ignored"

    # Add to ignore_list
    ignore_list = registry.setdefault("ignore_list", [])
    entry: dict[str, str] = {"pattern": project_id_or_path}
    if reason:
        entry["reason"] = reason

    # Avoid duplicates
    for existing in ignore_list:
        if isinstance(existing, dict) and existing.get("pattern") == project_id_or_path:
            save_projects(registry)
            return {"status": "already_ignored", "project_id": project_id_or_path}
        elif isinstance(existing, str) and existing == project_id_or_path:
            save_projects(registry)
            return {"status": "already_ignored", "project_id": project_id_or_path}

    ignore_list.append(entry)
    save_projects(registry)
    return {"status": "ignored", "project_id": project_id_or_path, "reason": reason}


def list_pending_projects() -> list[dict[str, Any]]:
    """List all projects with status=pending_confirmation."""
    registry = load_full_registry()
    projects = registry.get("projects", {})
    return [
        dict(proj)
        for proj in projects.values()
        if proj.get("status") == "pending_confirmation"
    ]


def get_ignore_list() -> list[dict[str, str]]:
    """Get the current ignore list from projects.yaml."""
    registry = load_full_registry()
    raw = registry.get("ignore_list", [])
    result: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            result.append({"pattern": entry, "reason": ""})
        elif isinstance(entry, dict):
            result.append({
                "pattern": entry.get("pattern", entry.get("path", "")),
                "reason": entry.get("reason", ""),
            })
    return result


def _profile_to_dict(profile: ProjectProfile) -> dict[str, Any]:
    """Convert a ProjectProfile to a plain dict for YAML storage."""
    return {
        "project_id": profile.project_id,
        "name": profile.name,
        "repo": profile.repo,
        "project_type": profile.project_type,
        "stack": profile.stack,
        "confidence": profile.confidence,
        "status": profile.status,
        "auto_generated": profile.auto_generated,
        "indicators": profile.indicators,
        "fingerprint": profile.fingerprint,
        "needs_refresh": profile.needs_refresh,
        "first_seen": profile.first_seen,
        "last_seen": profile.last_seen,
        "project_group": profile.project_group,
        "metadata": profile.metadata,
    }


def detect_project(repo_path: str | None = None, git_remote_url: str | None = None, cwd: str | None = None) -> ProjectMatch:
    base = Path(repo_path or cwd or ".").expanduser().resolve()
    projects = load_projects()

    marker = _find_marker(base)
    if marker:
        data = load_yaml(marker, {})
        project_id = data.get("project_id")
        if project_id in projects:
            return ProjectMatch(project_id, 1.0, ".ai-project.yaml", False, projects[project_id])
        return ProjectMatch(project_id, 0.8, ".ai-project.yaml", True, None)

    for project_id, project in projects.items():
        repo = Path(str(project.get("repo", ""))).expanduser()
        try:
            if repo.resolve() == base:
                return ProjectMatch(project_id, 1.0, "repo_path", False, project)
        except OSError:
            continue

    remote = git_remote_url or _git_remote(base)
    if remote:
        for project_id, project in projects.items():
            repo_remote = project.get("git_remote_url") or project.get("remote")
            if repo_remote and _normalize_remote(repo_remote) == _normalize_remote(remote):
                return ProjectMatch(project_id, 0.95, "git_remote", False, project)

    name = base.name.lower().replace("-", "_")
    for project_id, project in projects.items():
        candidates = {project_id.lower(), str(project.get("name", "")).lower().replace(" ", "_")}
        if name in candidates:
            return ProjectMatch(project_id, 0.65, "fuzzy_name", False, project)

    return ProjectMatch(None, 0.0, "none", True, None)


def _find_marker(start: Path) -> Path | None:
    current = start
    for candidate in [current, *current.parents]:
        marker = candidate / ".ai-project.yaml"
        if marker.exists():
            return marker
    return None


def _git_remote(path: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _normalize_remote(remote: str) -> str:
    return remote.strip().removesuffix(".git").lower()

