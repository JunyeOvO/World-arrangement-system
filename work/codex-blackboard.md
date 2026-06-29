# Codex Blackboard

## Current Task Goal

Maintain a project-local SAPIEN-Lite workflow for the World system repository.

## Scope Boundaries

- Work only inside this repository.
- Do not modify global Codex configuration.
- Do not install hooks.
- Do not write long-term memory.
- Do not overwrite any existing `AGENTS.md`.
- Do not change World architecture, routing, worker behavior, or runtime configuration while maintaining this workflow.
- Protect user changes in the git worktree; inspect status before staging, committing, or reverting.

## Project Context

World is a local multi-agent orchestration system. This repository already contains worker-facing AGENTS injection code under `orchestrator/agents_md.py` and `config/AGENTS.md.template`; that mechanism is separate from this local Codex workflow scaffold.

## Active Queue

| Date | Item | Status | Notes |
|---|---|---|---|
| 2026-06-29 | Add project-local SAPIEN-Lite workflow scaffold | Done | Created `work/` files only; no global config or hooks. |

## Risk Checks

Before any high-risk action, record the expected observation in `work/codex-verification-log.md`.

High-risk actions include:

- Recursive deletion or broad file moves.
- Writes outside this repository.
- Edits to global config, credentials, provider profiles, or runtime stores.
- Hook installation.
- Irreversible git operations.
- Publishing, deployment, or PR creation.

## Decision Notes

- Prefer additive local workflow files over root-level policy changes.
- If a root `AGENTS.md` is later required, propose an append-only patch first unless the user explicitly approves creation or modification.
