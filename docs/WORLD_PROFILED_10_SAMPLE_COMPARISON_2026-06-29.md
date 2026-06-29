# World Profiled 10-Sample Comparison Report

Date: 2026-06-29
Project: `travel_with_me`
Route: Claudecode / Deepseek-V4-flash

## Protocol Under Test

The third round used named `read_budget_profile` defaults instead of one flat budget:

| Sample group | Profile |
| --- | --- |
| Stack gate, AMap risk, unit scope, safe commands, E2E skip | `quick_triage` |
| 2D to 3D contract, routing regression, frontend state boundary | `code_contract_audit` |
| README onboarding | `docs_review` |
| Next World task candidates | `next_task_planning` |

All tasks still used:

```yaml
task_mode: read_only
expected_diff: false
verification_policy: changed_files_only
```

## Result Summary

| Metric | Round 1 unbudgeted | Round 2 flat budget | Round 3 named profiles |
| --- | ---: | ---: | ---: |
| Success rate | 100% | 80% | 90% |
| Rework rate | 0% | 20% | 10% |
| Adapter-compatible cost | $6.3185 | $4.1172 | $4.5409 |
| Backend token-calculated cost | not measured in report | not measured in report | $0.1285 |
| Average duration | 76.1s | 36.2s | 57.1s known rows |
| Worker turns | 121 | 92 | 93 known rows |
| Input tokens | 484,158 | 503,552 | 784,003 |
| Output tokens | 48,595 | 33,027 | 41,638 |
| Cache-read tokens | 1,524,864 | 1,264,384 | 2,526,336 |
| Project verification commands | 0 | 0 | 0 |
| Changed files | 0 | 0 | 0 |

Round 3 met the success-rate target, but with higher cost than Round 2. The profile approach repaired one of the two flat-budget failures, while preserving zero business-repo writes and zero accidental verification commands.

## Acceptance Against Target

| Target | Result | Pass |
| --- | ---: | --- |
| Success rate >= 90% | 90% | Yes |
| Rework rate <= 20% | 10% | Yes |
| Average duration < 60s | 57.1s known rows | Yes |
| Cost reduction >= 35% vs Round 1 | 28.1% adapter-compatible | No |
| No accidental project verification | 0 commands | Yes |
| Business repo clean | clean | Yes |

## Sample Matrix

| # | Sample | Profile | Task ID | Status | Adapter cost | Backend cost | Duration | Turns | Failure |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Stack and gate review | `quick_triage` | `t_20260629_125637_09520b` | `COMPLETED_WITH_ARTIFACTS` | $0.2615 | $0.0054 | 21.9s | 5 | success |
| 2 | 2D to 3D contract risk | `code_contract_audit` | `t_20260629_125703_bb4413` | `COMPLETED_WITH_ARTIFACTS` | $0.7105 | $0.0143 | 93.2s | 12 | success |
| 3 | AMap API risk | `quick_triage` | `t_20260629_125837_720370` | `COMPLETED_WITH_ARTIFACTS` | $0.4831 | $0.0097 | 52.3s | 10 | success |
| 4 | Unit test scope | `quick_triage` | `t_20260629_125931_fab6da` | `COMPLETED_WITH_ARTIFACTS` | $0.4382 | $0.0081 | 49.2s | 17 | success |
| 5 | Safe command classification | `quick_triage` | `t_20260629_130022_e683c1` | `COMPLETED_WITH_ARTIFACTS` | $0.4295 | $0.0074 | 66.5s | 15 | success |
| 6 | Routing regression candidate | `code_contract_audit` | `t_20260629_130129_5da368` | `COMPLETED_WITH_ARTIFACTS` | unavailable | $0.0414 | unavailable | unavailable | success; metrics parser recovered tokens |
| 7 | Frontend state boundary | `code_contract_audit` | `t_20260629_130547_5ef958` | `COMPLETED_WITH_ARTIFACTS` | $0.4571 | $0.0090 | 63.8s | 8 | success |
| 8 | E2E skip policy | `quick_triage` | `t_20260629_130651_5ff768` | `COMPLETED_WITH_ARTIFACTS` | $0.5211 | $0.0102 | 64.4s | 12 | success |
| 9 | README onboarding gaps | `docs_review` | `t_20260629_130757_6c732f` | `COMPLETED_WITH_ARTIFACTS` | $0.2564 | $0.0055 | 35.3s | 3 | success |
| 10 | Next World task candidates | `next_task_planning` | `t_20260629_130836_402707` | `FAILED_FINAL` | $0.9423 | $0.0175 | 66.8s | 11 | `max_turns_no_diff` |

## Findings

### 1. Named Profiles Improved Success

Round 2 failed on:

- `three_contract_budgeted`
- `world_next_tasks_budgeted`

Round 3 fixed the code contract failure by assigning `code_contract_audit`. The remaining failure is `next_task_planning`, which still ended in `max_turns_no_diff` even with 10 turns and 150 seconds.

### 2. The Remaining Failure Is a Task Shape Problem

`next_task_planning` asks the worker to inspect broad areas and synthesize three future patch candidates. This is not quick triage; it is planning plus prioritization. The current profile is wider, but the worker still failed to produce a final no-diff artifact before the turn limit.

Recommended adjustment:

```yaml
next_task_planning:
  max_files: 14
  max_dirs: 5
  max_worker_turns: 14
  max_duration_sec: 210
  max_output_tokens: 4500
```

Also require the worker to emit a partial result after the first candidate, so max-turn failures can still be salvaged as `COMPLETED_WITH_ARTIFACTS` when the task is read-only.

### 3. Metrics Parser Bug Found and Fixed

One successful task emitted many Claude Code `thinking_tokens` system events and assistant `message.usage` objects. The old parser did not aggregate `message.usage`, and it incorrectly treated `thinking_tokens` as a failure reason.

Fix implemented:

- aggregate `assistant.message.usage.input_tokens`
- aggregate `assistant.message.usage.output_tokens`
- aggregate `assistant.message.usage.cache_read_input_tokens`
- ignore `thinking_tokens` and `init` as failure reasons

The affected run now has recovered token metrics:

- input tokens: 277,356
- output tokens: 0
- cache-read tokens: 924,288

### 4. Cost Reporting Needs One Canonical Public Number

Round 1 and Round 2 reports used adapter-reported cost. The Console now uses backend token-calculated cost. These are materially different for the same calls.

Recommendation:

- Console primary: backend token-calculated cost.
- Artifact field: keep adapter-reported cost as `adapter_reported_cost_usd`.
- Reports: always label which cost basis is used.

## Decision

Named profiles are an improvement over a flat budget and are suitable to keep. They met success and duration targets, but did not meet the 35% adapter-compatible cost reduction target.

Before moving to patch tasks, tune `next_task_planning` and add partial-result salvage for read-only planning tasks.
