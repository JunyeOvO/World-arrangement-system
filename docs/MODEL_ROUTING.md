# World Router Model Routing

World Router V2 routes by features, labels, safety gates, candidate scores, and policy overrides. Keywords are inputs to classification, not final decisions by themselves.

## Agent + LLM Combinations

World Router only routes to these agent + LLM combinations:

| Combination | Internal agent | Internal LLM key | Use |
|---|---|---|---|
| claude code + deepseek V4 flash | `claude_code` | `deepseek_flash` | low-cost quick tasks |
| claude code + deepseek V4 pro | `claude_code` | `deepseek_pro` | default coding, docs, tests |
| claude code + Mimo V2.5 | `claude_code` | `mimo_v25` | multimodal/UI/design analysis |
| claude code + Mimo V2.5 pro | `claude_code` | `mimo_v25_pro` | multimodal-to-code and stronger MiMo coding tasks |
| opencode + GLM 5.2 | `opencode` | `opencode-go/glm-5.2` | complex coding, hard bugfixes, GLM escalation |
| codex review | `codex_review` | `codex_reviewer` | final World Review |

`selected_worker` and `selected_model` remain compatibility fields. New route payloads also include `selected_agent`, `selected_llm`, and `agent_llm`.

## Capability Tiers

Every valid agent + LLM combination uses the same tier vocabulary:

| Tier | Meaning |
|---|---|
| `default` | normal conservative execution |
| `high` | stronger reasoning/execution mode |
| `max` | highest allowed reasoning/execution mode |

`capability_tier` is the normalized tier in route output. `capability_profile` contains the tier plus execution settings. Non-tier resources are standardized at the top setting for every combination:

- `context_policy: top`
- `context_budget: max_available`
- `prompt_budget: max_available`
- `tool_budget: max_safe`
- `evidence_budget: max_safe`

Tier-specific behavior:

| Combination | `default` | `high` | `max` |
|---|---|---|---|
| claude code + deepseek V4 flash | low effort | medium effort | high effort |
| claude code + deepseek V4 pro | medium effort | high effort | max effort |
| claude code + Mimo V2.5 | medium effort | high effort | max effort |
| claude code + Mimo V2.5 pro | high effort | high effort | max effort |
| opencode + GLM 5.2 | omit `--variant` | `--variant high` | `--variant max` |
| codex review | high review effort | high review effort | max review effort |

## Hard Boundaries

- ClaudeCodeWorker only uses DeepSeek or MiMo.
- ClaudeCodeWorker never receives GLM, GLM-5.2, Z.AI GLM, or ChatGLM models.
- GLM-5.2 only runs through OpenCodeWorker with `opencode-go/glm-5.2`.
- MiMo does not run as a separate worker. MiMo V2.5 and MiMo V2.5 Pro run through Claude Code.
- Codex acts as World Entry and World Review. It is not a background Worker and never auto-merges.
- Hermes is not part of World routing.

## Default Routes

| Task | Agent + LLM | Internal route | Intensity / Variant |
|---|---|---|---|
| README, docs, comments | claude code + deepseek V4 pro / flash | `claude_code` + `deepseek_pro` or `deepseek_flash` | low / medium |
| Simple bugfix | claude code + deepseek V4 pro | `claude_code` + `deepseek_pro` | medium |
| Tests and low-risk code changes | claude code + deepseek V4 pro | `claude_code` + `deepseek_pro` | medium |
| High-risk code touching auth, payment, database, production, or deployment | claude code + deepseek V4 pro first, approval-aware escalation | `claude_code` + `deepseek_pro` | high |
| Screenshot / image / PDF / design analysis | claude code + Mimo V2.5 | `claude_code` + `mimo_v25` | medium |
| Screenshot-to-code task | claude code + Mimo V2.5 pro | `claude_code` + `mimo_v25_pro` | high |
| Explicit GLM-5.2 request | opencode + GLM 5.2 | `opencode` + `opencode-go/glm-5.2` | high |
| `complex_coding` / large refactor | opencode + GLM 5.2 or escalation chain | `opencode` + `opencode-go/glm-5.2` | high |
| `hard_bugfix` | opencode + GLM 5.2 | `opencode` + `opencode-go/glm-5.2` | max |

## Conflict Rules

- `README.md`, `docs/**`, and `*.md` tasks remain docs tasks even when they mention architecture, auth, or database concepts.
- Auth, payment, database, migration, production, and deployment become high risk only when the action is modify, refactor, migrate, delete, or deploy.
- Explicit GLM-5.2 requests have high routing priority but still pass through SafetyGate.
- `.env`, keys, credentials, destructive commands, force push, and merge commands are blocked before routing.

## OpenCode Variant Rules

For OpenCode, `capability_tier` is mapped to variants accepted by OpenCode:

- `default` means omit the `--variant` flag
- `high` means `--variant high`
- `max` means `--variant max`

World must never construct `--variant default`.

## Review and PR Gate

World Review checks the task, route, diff, worker result, risk warnings, and verification report. PR creation is allowed only after review approval and test success. World never auto-merges.
