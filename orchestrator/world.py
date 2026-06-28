"""World System naming constants.

Used across CLI, prompts, and docs for consistent branding.
Legacy names preserved for backward compatibility.
"""
from __future__ import annotations

# ── Primary brand names ──
WORLD_SYSTEM_NAME = "World System"
WORLD_SYSTEM_NAME_CN = "World 系统"

# ── Module names (brand) ──
WORLD_CORE = "World Core"
WORLD_ROUTER = "World Router"
WORLD_GUARD = "World Guard"
WORLD_WORKERS = "World Workers"
WORLD_REVIEW = "World Review"
WORLD_REGISTRY = "World Registry"
WORLD_WORKBENCH = "World Workbench"
WORLD_CLI = "World CLI"

# ── Legacy names (backward compat) ──
LEGACY_SYSTEM_NAME = "ai-orchestrator-v1"
LEGACY_CLI_NAME = "ai-dispatcher"

# ── One-line description ──
WORLD_TAGLINE = (
    f"{WORLD_SYSTEM_NAME_CN}是一个以 Codex 为入口、MCP Orchestrator 为调度核心，"
    "连接 Claude Code、OpenCode、Codex Review 等 Agent 与固定 LLM 组合的多模型全自动开发中枢。"
)

# ── Module mapping (brand → implementation) ──
WORLD_MODULE_MAP: dict[str, str] = {
    WORLD_CORE: "MCP Orchestrator",
    WORLD_ROUTER: "Router V2",
    WORLD_GUARD: "ApprovalGraph / RiskPolicy",
    WORLD_WORKERS: "Claude Code / OpenCode",
    WORLD_REVIEW: "Codex / GPT-5.5 final review",
    WORLD_REGISTRY: "Adaptive Project Layer",
    WORLD_WORKBENCH: "worktree / artifacts / diff",
    WORLD_CLI: LEGACY_CLI_NAME,
}
