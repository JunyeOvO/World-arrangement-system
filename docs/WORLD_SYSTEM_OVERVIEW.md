# World System Overview

> Legacy compatibility: this repository was originally named
> `ai-orchestrator-v1`. The CLI command remains `ai-dispatcher`.

## Position

World is a local execution backend for Codex-driven software work. Codex remains
the user-facing planner, dispatcher, and final judgment layer. World handles
bounded worker execution, evidence collection, verification, review artifacts,
token/cost accounting, and Console visibility.

World is intentionally not a fully autonomous production coding agent today:

- It does not auto-merge.
- It does not run high-risk changes without review.
- It treats read-only assistance as more mature than patch execution.
- It records evidence so Codex can make the final call.

## Architecture

```text
Codex (/world entry)
  |
  v
World CLI / MCP tools (ai-dispatcher)
  |
  v
World Core
  |- Router: task routing to agent + LLM combinations
  |- Guard: safety policy, approvals, forbidden paths
  |- Workers: Claude Code and OpenCode adapters
  |- Workbench: isolated worktree plus artifacts
  |- Verifier: test/build/evidence checks
  |- Review: Codex final review
  |- Registry: project detection and adaptation
  `- Console: status, tasks, metrics, cost, alerts
```

## Agent + LLM Combinations

| Combination | Internal agent | Internal LLM key | Role |
|---|---|---|---|
| claude code + deepseek V4 flash | `claude_code` | `deepseek_flash` | low-cost quick tasks |
| claude code + deepseek V4 pro | `claude_code` | `deepseek_pro` | default docs, tests, and ordinary coding |
| claude code + Mimo V2.5 | `claude_code` | `mimo_v25` | multimodal, UI, and design analysis |
| claude code + Mimo V2.5 pro | `claude_code` | `mimo_v25_pro` | stronger multimodal-to-code tasks |
| opencode + GLM 5.2 | `opencode` | `opencode-go/glm-5.2` | complex coding, hard bugfixes, escalation |
| codex review | `codex_review` | `codex_reviewer` | final World Review |

## Safety Boundaries

- ClaudeCodeWorker does not receive GLM.
- GLM-5.2 only runs through OpenCodeWorker.
- MiMo V2.5 and MiMo V2.5 Pro run through Claude Code, not an independent MiMo worker.
- World does not auto-merge.
- World must not read or write secrets.
- Archived sample reports are evidence, not current roadmap instructions.

## Current Docs

- `../PROJECT_STATUS.md`
- `../README.md`
- `README.md`
- `WORLD_CURRENT_UPGRADE_PLAN_AND_QUALITY_GATE_2026-07-01.md`
- `WORLD_EXECUTION_PROTOCOL.md`
- `MODEL_ROUTING.md`
- `WORLD_TOKEN_LEDGER_V1.md`
- `WORLD_PROJECT_MEMORY_V1.md`
