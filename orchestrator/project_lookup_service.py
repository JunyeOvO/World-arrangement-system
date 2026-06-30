from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .project_registry import ProjectMatch, detect_project, load_projects


class ProjectLookupService:
    """Lists and detects registered projects with health diagnostics."""

    def __init__(
        self,
        *,
        load_projects_func: Callable[[], dict[str, dict[str, Any]]] = load_projects,
        detect_project_func: Callable[..., ProjectMatch] = detect_project,
    ) -> None:
        self.load_projects = load_projects_func
        self.detect_project_func = detect_project_func

    def list_projects(self, query: str | None = None) -> dict[str, Any]:
        projects = self.load_projects()
        rows = list(projects.values())
        if query:
            q = query.lower()
            rows = [p for p in rows if q in p.get("project_id", "").lower() or q in p.get("name", "").lower()]
        return {"projects": rows}

    def detect_project(
        self,
        repo_path: str | None = None,
        git_remote_url: str | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        match = self.detect_project_func(repo_path=repo_path, git_remote_url=git_remote_url, cwd=cwd)
        health = project_registration_health(match.project, repo_path or cwd)
        return {
            "project_id": match.project_id,
            "confidence": match.confidence,
            "matched_by": match.matched_by,
            "needs_user": match.needs_user,
            "project": match.project,
            "health": health,
        }


def project_registration_health(project: dict[str, Any] | None, requested_repo_path: str | None = None) -> dict[str, Any]:
    if not project:
        return {"status": "unknown", "issues": ["project is not registered"], "warnings": []}
    issues: list[str] = []
    warnings: list[str] = []
    repo_raw = str(project.get("repo") or "")
    repo_path = Path(repo_raw).expanduser() if repo_raw else None
    if not repo_raw:
        issues.append("registered project has no repo path")
    elif not repo_path.exists():
        issues.append(f"registered repo path does not exist: {repo_raw}")
    requested = Path(requested_repo_path).expanduser().resolve() if requested_repo_path else None
    if requested and repo_path and repo_path.exists():
        try:
            if repo_path.resolve() != requested:
                issues.append(f"registered repo path differs from requested path: {repo_raw}")
        except OSError:
            issues.append(f"registered repo path cannot be resolved: {repo_raw}")
    if project.get("allow_auto_pr") is True:
        issues.append("allow_auto_pr is enabled; World deployment policy expects false unless explicitly approved")
    for key in ("test_commands", "build_commands"):
        value = project.get(key)
        if value is not None and not isinstance(value, list):
            issues.append(f"{key} must be a list")
        elif value == []:
            warnings.append(f"{key} is empty")
    return {
        "status": "needs_fix" if issues else "ok",
        "issues": issues,
        "warnings": warnings,
    }
