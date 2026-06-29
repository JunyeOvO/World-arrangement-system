# World Budgeted 10-Sample Comparison Report

Date: 2026-06-29
Project: `travel_with_me`
Route: Claudecode / Deepseek-V4-flash

## Protocol Under Test

Every sample used the explicit execution protocol:

```yaml
task_mode: read_only
expected_diff: false
verification_policy: changed_files_only
read_budget:
  max_files: 8
  max_dirs: 3
  max_worker_turns: 6
  max_duration_sec: 90
  max_output_tokens: 3000
```

The protocol was written into task artifacts and applied to route execution:

- `route.max_turns`: 6
- `route.timeout_sec`: 90
- project verification commands executed: 0
- changed files: 0

## Result Summary

| Metric | Previous 10-sample | Budgeted 10-sample | Change |
| --- | ---: | ---: | ---: |
| Success rate | 100% | 80% | -20 pts |
| Rework rate | 0% | 20% | +20 pts |
| Total cost | $6.3185 | $4.1172 | -34.84% |
| Average duration | 76.1s | 36.2s | -52.39% |
| Worker turns | 121 | 92 | -23.97% |
| Input tokens | 484,158 | 503,552 | +4.01% |
| Output tokens | 48,595 | 33,027 | -32.04% |
| Cache-read tokens | 1,524,864 | 1,264,384 | -17.08% |

The budget protocol substantially reduced time and cost, but the exact budget failed the success-rate acceptance target.

## Acceptance Against Target

| Target | Result | Pass |
| --- | ---: | --- |
| Success rate >= 90% | 80% | No |
| Rework rate <= 20% | 20% | Yes |
| Average duration < 60s | 36.2s | Yes |
| Total cost reduction >= 35% | 34.84% | Nearly, but no |
| No accidental project verification | 0 commands | Yes |
| Business repo clean | clean | Yes |

## Sample Matrix

| # | Sample | Task ID | Status | Cost | Duration | Turns | Failure |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | Stack and gate review | `t_20260629_123433_6e8381` | `COMPLETED_WITH_ARTIFACTS` | $0.2491 | 17.1s | 6 | success |
| 2 | 2D to 3D contract risk | `t_20260629_123455_d29f50` | `FAILED_FINAL` | $0.5299 | 23.6s | 7 | `max_turns_no_diff` |
| 3 | AMap API risk | `t_20260629_123523_815871` | `COMPLETED_WITH_ARTIFACTS` | $0.4926 | 47.2s | 11 | success |
| 4 | Unit test scope | `t_20260629_123613_45ac4a` | `COMPLETED_WITH_ARTIFACTS` | $0.3833 | 32.7s | 12 | success |
| 5 | Safe command classification | `t_20260629_123650_bbe1be` | `COMPLETED_WITH_ARTIFACTS` | $0.4233 | 58.8s | 19 | success |
| 6 | Routing regression candidate | `t_20260629_123750_0870c4` | `COMPLETED_WITH_ARTIFACTS` | $0.3469 | 23.1s | 7 | `error_max_turns`, salvaged artifact |
| 7 | Frontend state boundary | `t_20260629_123817_b2438d` | `COMPLETED_WITH_ARTIFACTS` | $0.4875 | 57.0s | 10 | success |
| 8 | E2E skip policy | `t_20260629_123915_61780f` | `COMPLETED_WITH_ARTIFACTS` | $0.4602 | 45.7s | 10 | success |
| 9 | README onboarding gaps | `t_20260629_124002_6020c9` | `COMPLETED_WITH_ARTIFACTS` | $0.2648 | 31.2s | 3 | success |
| 10 | Next World task candidates | `t_20260629_124035_4d4ae2` | `FAILED_FINAL` | $0.4796 | 25.7s | 7 | `max_turns_no_diff` |

## Findings

### 1. The Protocol Works

The explicit fields were correctly applied. Every task carried the expected protocol values, every route used the budgeted timeout and turn limit, and no project test/build commands ran for read-only tasks.

This confirms that `task_mode`, `expected_diff`, `verification_policy`, and `read_budget` are now usable as a real execution contract, not just prompt text.

### 2. The Budget Is Too Tight for Synthesis Tasks

The two hard failures both required synthesis across multiple code areas:

- 2D selected workArea to 3D diorama contract analysis.
- Selecting 3 next real World patch candidates.

Both failed with `max_turns_no_diff`. These were not verification failures and not business-repo write failures. The worker simply did not reach a final answer within the turn budget.

### 3. Current Turn Accounting Is Not a Hard Global Cap

Several successful tasks reported turns above 6. The route contained `max_turns=6`, but worker metrics can still show higher turn counts depending on provider/tool event accounting. This means `max_worker_turns` is useful but not yet a perfect hard limiter across all worker/runtime modes.

### 4. Cost Target Was Almost Met

Total cost dropped from $6.3185 to $4.1172, a 34.84% reduction. The target was 35%, so this is effectively at the threshold but should be treated as not passed.

The stronger win was duration: average task time dropped by 52.39%.

## Decision

The explicit budget protocol is valuable, but the single flat budget is not production-ready.

Use budget tiers by task type instead:

```yaml
read_budget_profiles:
  quick_triage:
    max_files: 6
    max_dirs: 2
    max_worker_turns: 6
    max_duration_sec: 90
    max_output_tokens: 2500
  code_contract_audit:
    max_files: 10
    max_dirs: 4
    max_worker_turns: 10
    max_duration_sec: 150
    max_output_tokens: 4000
  next_task_planning:
    max_files: 12
    max_dirs: 4
    max_worker_turns: 10
    max_duration_sec: 150
    max_output_tokens: 4000
```

## Recommended Next Step

Implement named `read_budget_profile` support:

- `quick_triage`
- `code_contract_audit`
- `next_task_planning`
- `docs_review`

Then rerun only the 2 failed categories plus 2 representative successful categories. Acceptance target for the tuning run:

- 4 / 4 success.
- Total cost stays below $2.00.
- No project verification commands.
- No business-repo writes.

If that passes, move to the next phase: 3 real low-risk patch tasks.
