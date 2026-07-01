# World Post-Fix 10-Sample Quality Matrix Report

Date: 2026-06-29
Project: `travel_with_me`
Mode: real worker execution, low-risk, read-only, zero business-repo writes
Route: Claudecode / Deepseek-V4-flash

## Executive Summary

The post-fix sample passed the MVP read-only quality gate.

- Samples: 10
- Terminal success: 10 / 10
- Quality outcome: 10 `success`, 10 `verified`, 10 `accepted`
- Rework required: 0 / 10
- Project verification commands executed: 0
- Changed files: 0
- Business repository status before and after: clean
- Total measured worker cost: $6.3185
- Total measured input tokens: 484,158
- Total measured output tokens: 48,595
- Total measured cache-read tokens: 1,524,864
- Total worker turns: 121
- Average duration: 76,060 ms

The two fixes from the previous evaluation were validated:

1. Read-only tasks no longer fall into expensive no-diff fallback when they produce useful artifacts.
2. Test command recommendations and filenames such as `vitest.config.js` / `playwright.config.js` no longer trigger actual project test execution.

## Sample Matrix

| # | Sample | Task ID | Status | Quality | Cost | Duration | Turns | Input | Output | Cache read |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Stack and gate review | `t_20260629_112656_5b5eec` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.2610 | 21.6s | 5 | 33,868 | 1,687 | 61,312 |
| 2 | 2D to 3D contract risk | `t_20260629_112721_65bb24` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.7105 | 81.2s | 8 | 75,932 | 8,267 | 226,944 |
| 3 | AMap API risk | `t_20260629_112841_5a3e38` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.4717 | 42.9s | 12 | 61,686 | 4,371 | 74,112 |
| 4 | Unit test scope | `t_20260629_112926_2b3f62` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.6190 | 84.0s | 32 | 49,334 | 8,881 | 275,840 |
| 5 | Safe command classification | `t_20260629_113050_cf0c3e` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.4362 | 52.4s | 19 | 42,820 | 5,747 | 133,632 |
| 6 | Routing regression candidate | `t_20260629_113145_a61be5` | `COMPLETED_WITH_ARTIFACTS` | verified | $1.5885 | 207.6s | 13 | 37,414 | 4,846 | 353,920 |
| 7 | Frontend state boundary | `t_20260629_113507_ca9653` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.3396 | 35.8s | 3 | 48,797 | 2,761 | 27,392 |
| 8 | E2E skip policy | `t_20260629_113545_3e212a` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.5153 | 48.6s | 13 | 62,642 | 4,539 | 152,576 |
| 9 | README onboarding gaps | `t_20260629_113635_c24519` | `COMPLETED_WITH_ARTIFACTS` | verified | $0.2543 | 28.3s | 3 | 33,390 | 2,376 | 27,520 |
| 10 | Next World task candidates | `t_20260629_113706_66eb23` | `COMPLETED_WITH_ARTIFACTS` | verified | $1.1223 | 158.1s | 13 | 38,275 | 5,120 | 191,616 |

## Quality Findings

### What Worked

- World correctly kept all 10 tasks in read-only mode.
- No task touched the business repository.
- No project test commands were accidentally executed.
- Each task produced a structured artifact that can be reviewed without opening the whole repo manually.
- Outcome recording now gives a useful acceptance signal instead of only raw status.

### What Still Needs Optimization

The quality gate passed, but cost variance is too high.

The expensive samples were:

- `routing_regression`: $1.5885, 207.6s, 353,920 cache-read tokens.
- `world_next_tasks`: $1.1223, 158.1s, 191,616 cache-read tokens.
- `three_contract`: $0.7105, 81.2s, 226,944 cache-read tokens.
- `unit_scope`: 32 turns, 8,881 output tokens.

These tasks are still low risk, but their scope allows too much repository exploration. For the MVP to save Codex quota reliably, World needs explicit read budgets.

Recommended budget fields:

```yaml
read_budget:
  max_files: 8
  max_dirs: 3
  max_worker_turns: 8
  max_duration_sec: 90
  max_output_tokens: 4000
```

## Does This Save Codex Work?

Yes, for read-only triage and project-understanding tasks.

This run offloaded 10 bounded investigations to World workers and returned structured artifacts, route metrics, quality outcomes, and costs. Codex did not need to manually read the project files for each task. That is the right MVP behavior.

However, it is not yet enough to claim the target of extending Codex quota from 2 days to 7 days across all development work.

Current evidence supports:

- Strong fit: project audits, test gate selection, dependency risk review, onboarding gaps, next-task planning.
- Medium fit: narrow bug candidate discovery when scope is tightly bounded.
- Not yet proven: automatic patch generation, multi-file implementation, full test repair, visual/UI regression fixing.

To reach the 2-day to 7-day quota goal, Codex must stay below about 28.6% of prior direct-work usage. This sample shows the execution model can avoid direct Codex repo analysis, but it also shows World workers need stricter budgets so cheap read-only tasks do not become long exploratory sessions.

## Recommended Next Step

Implement a `read_budget` and `task_mode` contract in the dispatcher and worker prompt:

- `task_mode: read_only | patch | test | docs | audit`
- `expected_diff: true | false`
- `verification_policy: none | changed_files_only | unit | full`
- `read_budget.max_files`
- `read_budget.max_worker_turns`
- `read_budget.max_duration_sec`
- `read_budget.max_output_tokens`

Then run a second 10-sample matrix with identical task categories and compare:

- Success rate should remain at or above 90%.
- Rework rate should remain below 20%.
- Average duration should drop below 60 seconds.
- Total cost should drop by at least 35%.
- No accidental project verification should occur for read-only tasks.

## Decision

World MVP is usable for read-only assistance in real projects after the post-fix changes.

It should now move from "quality matrix exists" to "budgeted execution protocol" before expanding into real patch tasks.
