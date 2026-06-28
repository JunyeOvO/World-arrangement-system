from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .project_fingerprint import compute_fingerprint, has_changed
from .project_profiler import profile_project
from .project_registry import (
    load_full_registry,
    load_projects,
    register_project_to_yaml,
    save_projects,
)
from .types import ProjectProfile


def refresh_project_profile(project_id: str, force: bool = False) -> dict[str, Any]:
    """Refresh the profile of an already-registered project.

    Re-profiles the repo, recomputes fingerprint, and updates projects.yaml
    if auto_generated or if fingerprint changed.
    """
    projects = load_projects()
    if project_id not in projects:
        return {"status": "not_found", "project_id": project_id, "message": "project not registered"}

    existing = projects[project_id]
    repo_path = existing.get("repo", "")
    if not repo_path:
        return {"status": "error", "project_id": project_id, "message": "project has no repo path"}

    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        return {"status": "error", "project_id": project_id, "message": f"repo path does not exist: {repo}"}

    # Re-profile
    new_profile = profile_project(repo)
    new_profile.project_id = project_id  # Preserve original project_id

    # Recompute fingerprint
    fingerprint = compute_fingerprint(repo, project_id)
    new_profile.fingerprint = fingerprint.hash

    # Check if structure changed
    old_fingerprint = existing.get("fingerprint", "")
    if old_fingerprint and has_changed(old_fingerprint, fingerprint.hash):
        new_profile.needs_refresh = True

    # Preserve user overrides if project is manually managed
    is_auto = existing.get("auto_generated", False)
    if not is_auto and not force:
        # Only update timestamp and fingerprint
        existing["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        existing["fingerprint"] = fingerprint.hash
        if has_changed(old_fingerprint, fingerprint.hash):
            existing["needs_refresh"] = True
        registry = load_full_registry()
        registry["projects"][project_id] = existing
        save_projects(registry)
        return {
            "status": "updated",
            "project_id": project_id,
            "fingerprint_changed": has_changed(old_fingerprint, fingerprint.hash),
            "needs_refresh": existing.get("needs_refresh", False),
            "message": "user-managed project, fingerprint updated",
        }

    # Auto-generated: full update
    result = register_project_to_yaml(new_profile, force=True)
    result["fingerprint_changed"] = has_changed(old_fingerprint, fingerprint.hash)
    result["needs_refresh"] = new_profile.needs_refresh
    return result


def batch_refresh(project_ids: list[str] | None = None) -> dict[str, Any]:
    """Refresh all auto-generated projects, or a specific list."""
    all_projects = load_projects()

    if project_ids:
        targets = {pid: all_projects[pid] for pid in project_ids if pid in all_projects}
    else:
        targets = {
            pid: proj
            for pid, proj in all_projects.items()
            if proj.get("auto_generated", False)
        }

    results: dict[str, Any] = {}
    refreshed = 0
    needs_refresh_list: list[str] = []

    for project_id in targets:
        result = refresh_project_profile(project_id)
        results[project_id] = result
        if result.get("status") in ("updated", "registered"):
            refreshed += 1
        if result.get("needs_refresh"):
            needs_refresh_list.append(project_id)

    return {
        "total": len(targets),
        "refreshed": refreshed,
        "needs_refresh": needs_refresh_list,
        "details": results,
    }


def mark_refreshed(project_id: str) -> dict[str, Any]:
    """Manually clear the needs_refresh flag for a project."""
    registry = load_full_registry()
    projects = registry.get("projects", {})

    if project_id not in projects:
        return {"status": "not_found", "project_id": project_id}

    projects[project_id]["needs_refresh"] = False
    projects[project_id]["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_projects(registry)
    return {"status": "refreshed", "project_id": project_id}
