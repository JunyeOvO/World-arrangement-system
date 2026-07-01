# World Arrangement System

> Legacy compatibility: this repository was originally named `ai-orchestrator-v1`. The Python CLI command is still `ai-dispatcher`.

World is a local multi-agent development orchestration system for Codex-driven software work. Codex stays as the human-facing planner and dispatcher, while World routes bounded project tasks to local worker agents, records evidence, runs verification, and returns reviewable artifacts.

The core goal is practical: reduce Codex main-thread work by moving execution, verification, model routing, and evidence collection into a controlled local system. World measures real worker LLM token usage and cost, and separately estimates Codex planning/review token pressure so the system can be tuned toward longer Codex quota availability.

## What World Does

- Detects and registers real local projects.
- Accepts structured tasks from Codex through `/world`.
- Routes work across supported agent/model combinations.
- Runs workers in isolated task directories and worktrees.
- Tracks task state, process liveness, artifacts, review, and verification.
- Computes real worker model cost from recorded input/output/cache tokens.
- Displays system health, tasks, model usage, token cost, and Codex budget pressure in a local Web Console.
- Keeps business repositories clean by storing World runtime data outside the project when configured.

World can create diffs, patches, and PR-ready artifacts. It does **not** automatically merge changes.

## Current Architecture

```text
Codex /world skill
  -> ai-dispatcher CLI or MCP tools
  -> World Core orchestrator
  -> Router + approval policy + worktree control
  -> Claudecode / Opencode workers
  -> Verify + World Review
  -> artifacts, metrics, Console, patch or PR
```

Main directories:

```text
orchestrator/         Python package, CLI, MCP server, scheduler, router, console API
console-web/          React/Vite Web Console frontend
config/               user-level config templates
profiles/             provider env profile examples only, no real keys
prompts/              worker and review prompts
schemas/              JSON schema contracts
scripts/              helper scripts
tests/                pytest suite
docs/                 architecture, rollout plans, status design, capability reports
```

## Supported Agent / Model Names

The Console normalizes displayed names to:

| Agent | Models |
|---|---|
| Claudecode | Deepseek-V4-flash, Deepseek-V4-pro, Mimo-V2.5, Mimo-V2.5-pro |
| Opencode | GLM-5.2 |

OpenCode owns GLM provider access. Claude Code provider profiles are loaded per worker subprocess so model environments do not overwrite each other globally.

## Install

Windows PowerShell:

```powershell
cd C:\Users\fujunye\Documents\World系统
uv sync --all-extras --dev
```

Linux/macOS style shell:

```bash
cd /path/to/World-arrangement-system
uv sync --all-extras --dev
```

Create user-level config from examples:

```bash
mkdir -p ~/.ai-orchestrator ~/.world
cp config/projects.yaml.example ~/.ai-orchestrator/projects.yaml
cp config/models.yaml.example ~/.ai-orchestrator/models.yaml
cp config/policies.yaml.example ~/.ai-orchestrator/policies.yaml
```

Then edit `~/.ai-orchestrator/projects.yaml` so each `repo` points to a real git repository.

Do not commit provider keys. Keep real `.env` files, provider profiles, logs, worker outputs, and runtime stores outside git.

## Codex Skills

World is split into two Codex skills:

| Skill | Purpose |
|---|---|
| `/worldsetup` | Deploy, bootstrap, register, repair, or health-check World integration for a project. |
| `/world` | Execute tasks on an already registered project through World. |

Recommended task entry:

```text
/world task
project: travel_with_me
mode: execute
world_preflight: minimal
world_self_analysis: false

目标：
修复一个明确的业务开发问题。

验收标准：
- 说明应修改哪些行为。
- 运行相关测试或说明无法运行的原因。
- 返回变更文件、测试结果、风险、下一步。

安全约束：
- 不读不输出 secrets。
- 不改 .env、缓存、运行日志、worker 产物。
- 不自动 merge。
```

The intended `/world` fast path is:

1. Check `git status`.
2. Run project detection.
3. Submit a structured task to World.
4. Read status/result/artifacts.
5. Report outcome to the user.

`/world` should treat World as the execution backend, not as the subject being analyzed.

## CLI Quick Start

Health check:

```bash
uv run ai-dispatcher doctor
```

Detect a project:

```bash
uv run ai-dispatcher detect-project --repo-path /path/to/project
```

Submit a dry-run task:

```bash
uv run ai-dispatcher submit-task --project generic --goal "只读分析项目结构" --dry-run
```

Run tests:

```bash
uv run pytest
```

## Web Console

Start the local Console:

```bash
uv run ai-dispatcher serve-console --host 127.0.0.1 --port 8765
```

Open:

[http://127.0.0.1:8765/](http://127.0.0.1:8765/)

Console capabilities:

- Top status strip: Running, Queued, Failed, Approval, Alerts, Cost.
- Process cards for current actionable tasks.
- Task detail with timeline, route, verify, review, artifacts, and Markdown output preview.
- Metrics dashboard with usage summary, model window, cost chart, call table, efficiency, and Codex budget.
- Delete/dismiss actions for Failed and Approval task cards.
- Real worker token and cost display from backend computation.

The Metrics page currently includes:

- Attempts
- Total cost
- P95 duration with automatic time units
- Efficiency
- Cost by model
- Model call table
- Codex Budget

## Token And Cost Accounting

World separates measured worker usage from estimated Codex usage.

Measured:

- Worker input tokens
- Worker output tokens
- Worker cache-read input tokens
- Worker model cost computed by backend pricing
- Same-token GLM-5.2 reference baseline
- Savings amount and savings percentage

Estimated:

- Codex planning/dispatch tokens
- Codex review tokens
- Actual Codex review subset when Codex review is available

Codex estimates use a local deterministic estimator (`utf8_bytes_div_4`) because this environment does not expose official Codex quota telemetry. They are useful for trend control and quota-pressure design, but they are not official Codex usage.

The product target is to reduce Codex main-thread usage enough that a weekly quota that currently lasts about 2 days can last 7 days. That requires roughly:

- 3.5x effective extension
- 71.43% Codex-side reduction
- 28.57% maximum remaining Codex share

## Worker Execution On Windows

World Core can run from Windows, but real Claude Code and OpenCode workers are commonly invoked through WSL:

```powershell
$env:AI_CLAUDE_CMD = "wsl -e claude"
$env:AI_OPENCODE_CMD = "wsl -e opencode"
```

If your commands differ, set the overrides before running real workers.

## Safety Rules

World is designed to keep automation bounded:

- Never commit API keys.
- Never submit `profiles/*.env`.
- Never submit `.claude/settings.local.json`.
- Never submit `.venv/`, `.pytest_cache/`, `__pycache__/`, `worker/`, logs, or runtime outputs.
- Keep only `.env.example` and `profiles/*.env.example` in git.
- Do not auto-merge.
- Block or surface forbidden path changes.
- Redact secret-like fields before returning Console data.

## Status Model

World keeps raw execution states separate from dashboard grouping.

Top-level dashboard groups:

- Running: fresh live worker/control heartbeat.
- Queued: accepted and can continue without user input.
- Failed: terminal or actionable failures.
- Approval: user approval/input/review required.
- Alerts: stale or anomalous runtime-derived states.
- None: completed, cancelled, dismissed, or non-actionable records.

This prevents stale `EXECUTING` rows from appearing as truly running when the worker process has already finished or disappeared.

## Useful Docs

- `docs/WORLD_CURRENT_UPGRADE_PLAN_AND_QUALITY_GATE_2026-07-01.md`
- `docs/WORLD_EXECUTION_PROTOCOL.md`
- `docs/WORLD_SYSTEM_OVERVIEW.md`
- `docs/CODEX_ENTRY.md`
- `docs/LIGHTWEIGHT_DEPLOYMENT.md`
- `docs/MODEL_ROUTING.md`
- `docs/WORKER_CONTRACT.md`
- Historical upgrade plans, samples, scans, and old gate reports are archived in
  `docs/archive/obsolete-2026-07-01/`.

## Current Boundary

World is useful today for:

- Project quality audits.
- Root-cause investigation.
- Small and medium bug fixes.
- Documentation and test updates.
- Focused UI fixes.
- Repeated tasks where routing and context compression matter.

World should still be treated carefully for:

- Large autonomous feature delivery.
- Auth, payment, production database, or security-sensitive changes.
- Multi-repo changes.
- Tasks without reproducible local tests.
- Claims of measured Codex quota savings before enough Codex usage ledger data exists.

## Repository Hygiene

Before pushing:

```bash
uv run pytest
rg -n "sk-[A-Za-z0-9_-]{16,}|API_KEY|SECRET|TOKEN|PASSWORD" -g "!*.example" -g "!uv.lock" .
git status --short --branch
```

Expected result: tests pass, no real secrets, and only intentional files are staged.
