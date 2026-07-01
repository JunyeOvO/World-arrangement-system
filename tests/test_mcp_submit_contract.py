from __future__ import annotations

import sys
import types
from typing import Any


class FakeFastMCP:
    def __init__(self, name: str, instructions: str) -> None:
        self.name = name
        self.instructions = instructions
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorate(func):
            self.tools[func.__name__] = func
            return func

        return decorate


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str):
        def call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"method": name, "args": args, "kwargs": kwargs})
            return {"method": name, "args": args, "kwargs": kwargs}

        return call


def _install_fake_mcp(monkeypatch):
    fake_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)


def test_mcp_submit_task_exposes_dry_run_and_forced_route(monkeypatch):
    _install_fake_mcp(monkeypatch)
    from orchestrator import mcp_server

    service = FakeService()
    monkeypatch.setattr(mcp_server, "OrchestratorService", lambda: service)

    mcp = mcp_server.create_server()
    result = mcp.tools["submit_task"](
        "demo",
        "inspect",
        dry_run=True,
        force_worker="opencode",
        force_model="opencode_go_glm52",
        force_variant="high",
    )

    assert result["method"] == "submit_task"
    assert result["args"][:8] == (
        "demo",
        "inspect",
        "medium",
        True,
        False,
        True,
        "opencode",
        "opencode_go_glm52",
    )
    assert result["args"][8] == "high"


def test_mcp_submit_current_project_task_exposes_dry_run_and_forced_route(monkeypatch):
    _install_fake_mcp(monkeypatch)
    from orchestrator import mcp_server

    service = FakeService()
    monkeypatch.setattr(mcp_server, "OrchestratorService", lambda: service)

    mcp = mcp_server.create_server()
    result = mcp.tools["submit_current_project_task"](
        "C:/repo",
        "inspect",
        dry_run=True,
        force_worker="claude_code",
        force_model="deepseek_pro",
        force_variant="max",
    )

    assert result["method"] == "submit_current_project_task"
    assert result["args"][:8] == (
        "inspect",
        "C:/repo",
        "medium",
        True,
        False,
        True,
        "claude_code",
        "deepseek_pro",
    )
    assert result["args"][8] == "max"
