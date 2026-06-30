from __future__ import annotations

from typing import Any

from .project_commands import (
    handle_confirm_project_profile,
    handle_discover_projects,
    handle_ignore_project,
    handle_list_unregistered_projects,
    handle_profile_project,
    handle_refresh_project_profile,
    handle_register_project,
    handle_scan_project_roots,
)


class ProjectCommandService:
    """Facade for project discovery and registry commands."""

    def scan_project_roots(self, roots: list[str] | None = None, max_depth: int = 3) -> dict[str, Any]:
        return handle_scan_project_roots(roots, max_depth)

    def discover_projects(self, roots: list[str] | None = None, max_depth: int = 3) -> dict[str, Any]:
        return handle_discover_projects(roots, max_depth)

    def profile_project(self, repo_path: str, force: bool = False) -> dict[str, Any]:
        return handle_profile_project(repo_path, force)

    def register_project(self, repo_path: str, confirm: bool = False) -> dict[str, Any]:
        return handle_register_project(repo_path, confirm)

    def refresh_project_profile(self, project_id: str) -> dict[str, Any]:
        return handle_refresh_project_profile(project_id)

    def list_unregistered_projects(self) -> dict[str, Any]:
        return handle_list_unregistered_projects()

    def confirm_project_profile(self, project_id: str) -> dict[str, Any]:
        return handle_confirm_project_profile(project_id)

    def ignore_project(self, repo_path: str, reason: str = "") -> dict[str, Any]:
        return handle_ignore_project(repo_path, reason)
