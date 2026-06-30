from __future__ import annotations

from typing import Any

import orchestrator.project_command_service as module
from orchestrator.project_command_service import ProjectCommandService


def test_project_command_service_delegates_scan_and_discover(monkeypatch):
    calls: list[tuple[str, tuple[Any, ...]]] = []

    monkeypatch.setattr(
        module,
        "handle_scan_project_roots",
        lambda roots, max_depth: calls.append(("scan", (roots, max_depth))) or {"status": "scan"},
    )
    monkeypatch.setattr(
        module,
        "handle_discover_projects",
        lambda roots, max_depth: calls.append(("discover", (roots, max_depth))) or {"status": "discover"},
    )
    service = ProjectCommandService()

    assert service.scan_project_roots(["C:/repo"], 2) == {"status": "scan"}
    assert service.discover_projects(["C:/repo"], 3) == {"status": "discover"}
    assert calls == [
        ("scan", (["C:/repo"], 2)),
        ("discover", (["C:/repo"], 3)),
    ]


def test_project_command_service_delegates_profile_and_registry_commands(monkeypatch):
    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(
        module,
        "handle_profile_project",
        lambda repo_path, force: calls.append(("profile", (repo_path, force))) or {"status": "profile"},
    )
    monkeypatch.setattr(
        module,
        "handle_register_project",
        lambda repo_path, confirm: calls.append(("register", (repo_path, confirm))) or {"status": "register"},
    )
    monkeypatch.setattr(
        module,
        "handle_refresh_project_profile",
        lambda project_id: calls.append(("refresh", (project_id,))) or {"status": "refresh"},
    )
    monkeypatch.setattr(
        module,
        "handle_list_unregistered_projects",
        lambda: calls.append(("list", ())) or {"status": "list"},
    )
    monkeypatch.setattr(
        module,
        "handle_confirm_project_profile",
        lambda project_id: calls.append(("confirm", (project_id,))) or {"status": "confirm"},
    )
    monkeypatch.setattr(
        module,
        "handle_ignore_project",
        lambda repo_path, reason: calls.append(("ignore", (repo_path, reason))) or {"status": "ignore"},
    )
    service = ProjectCommandService()

    assert service.profile_project("C:/repo", True) == {"status": "profile"}
    assert service.register_project("C:/repo", True) == {"status": "register"}
    assert service.refresh_project_profile("project_1") == {"status": "refresh"}
    assert service.list_unregistered_projects() == {"status": "list"}
    assert service.confirm_project_profile("project_1") == {"status": "confirm"}
    assert service.ignore_project("C:/repo", "scratch") == {"status": "ignore"}
    assert calls == [
        ("profile", ("C:/repo", True)),
        ("register", ("C:/repo", True)),
        ("refresh", ("project_1",)),
        ("list", ()),
        ("confirm", ("project_1",)),
        ("ignore", ("C:/repo", "scratch")),
    ]
