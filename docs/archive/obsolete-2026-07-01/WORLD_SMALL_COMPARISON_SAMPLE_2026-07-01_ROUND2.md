# World Small Comparison Sample - 2026-07-01 Round 2

Scope: small real read-only comparison sample for `travel_with_me`, run after
the previous 6-task seeded sample. This round checks whether the current
executor controls still complete bounded production-like investigations without
business-repo writes.

Project under test: `travel_with_me`

All tasks used:

- `worker=claude_code`
- `model=deepseek_flash`
- `task_mode=read_only`
- `expected_diff=false`
- `verification_policy=changed_files_only`
- `auto_pr=false`
- no business repo writes

## Summary

| Metric | Previous 6-task sample | This 4-task sample |
| --- | ---: | ---: |
| Worker tasks | 6 | 4 |
| Completed | 6 | 4 |
| Failed | 0 | 0 |
| Success rate | 100.0% | 100.0% |
| Verified quality outcomes | 6 | 4 |
| Accepted outcomes | 6 | 4 |
| Adapter-reported worker cost | $3.098607 | $2.025572 |
| Backend calculated worker cost | not recorded in previous report | $0.035829 |
| Total duration | 330398 ms | 259318 ms |
| Average duration | 55066 ms | 64830 ms |
| Worker turns | 56 | 36 |
| Average worker turns | 9.33 | 9.00 |
| Worker input tokens | 288866 | 195911 |
| Worker output tokens | 34332 | 22327 |
| Worker cache-read tokens | 1278464 | 767744 |
| Estimated Codex planning/review tokens | not recorded in previous report | 1831 |
| `silent_max_turns_no_output` failures | 0 | 0 |
| Business repo changed files | 0 | 0 |

The small-sample result remains healthy: all four tasks completed, all outcomes
were verified and accepted, no read-only task changed files, and no silent
max-turn failure appeared.

The comparison is directional rather than statistically strong because this
round intentionally used only four tasks. Efficiency improved slightly on turns
per task and cache-read tokens per task, but average duration regressed because
the `code_contract_audit` sample still took about 100 seconds.

## Task Matrix

| # | Name | Profile | Task ID | Status | Quality | Turns | Duration | Adapter Cost | Backend Cost | Input | Output | Cache read | Codex est. |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `quick_runtime_health_recheck` | `quick_triage` | `t_20260701_005020_7d43da` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 9 | 37745 ms | $0.374434 | $0.007187 | 42975 | 3027 | 115328 | 461 |
| 2 | `area_contract_regression_check` | `code_contract_audit` | `t_20260701_005100_68d004` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 11 | 99900 ms | $0.799516 | $0.013276 | 68856 | 8912 | 407552 | 469 |
| 3 | `docs_command_consistency_check` | `docs_review` | `t_20260701_005239_6fca3d` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 8 | 61882 ms | $0.415142 | $0.007024 | 35669 | 5857 | 139264 | 443 |
| 4 | `next_p0_candidate_planning` | `next_task_planning` | `t_20260701_005342_01c151` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 8 | 59791 ms | $0.436480 | $0.008342 | 48411 | 4531 | 105600 | 458 |

## Validation Evidence

- `detect-project --repo-path C:\Users\fujunye\Desktop\Agent\travel_with_me`
  returned `project_id=travel_with_me`, confidence `1.0`, and health `ok`.
- `git -C C:\Users\fujunye\Desktop\Agent\travel_with_me status --short --branch`
  remained clean before and after the run.
- Every task produced `final.md`, `metrics.json`, `outcome.json`,
  `token_ledger.json`, and `verify/verify.json`.
- Every task reported `changed_files=[]`.
- Worker streams did not contain `silent_max_turns_no_output` or
  `error_max_turns`.

## Findings From Worker Outputs

1. Runtime health check passed overall, but `playwright.config.js` uses
   `npm.cmd start` as the webServer command. This is Windows-specific and is a
   latent Linux/WSL/CI portability risk.
2. The selected/workArea contract chain is currently coherent. Remaining risks
   are low: inconsistent object identity from `resolveAnchored3DWorkArea` on
   adjusted vs no-op paths, a dead `seen` set in anchor dedupe code, unvalidated
   profile passthrough, and limited logging when anchoring is skipped.
3. README onboarding is usable for install/start, but the test/check section is
   stale. `npm run check` is described too narrowly, `tests/e2e` is shown under
   the wrong directory path, and several test scripts are undocumented.
4. The single next candidate produced by `next_task_planning` is to promote
   golden screenshot assertions from opt-in to default-on, with an opt-out for
   local non-visual iteration.

## Codex Workload Assessment

This round supports the current hypothesis that World can offload bounded
read-only investigation from the Codex main thread:

- Worker-side real token use: 195911 input, 22327 output, 767744 cache-read.
- Codex-side estimated planning/review tokens: 1831.
- Approximate Codex share of counted tokens: about 0.19% when cache-read tokens
  are included, or about 0.84% using only worker input+output tokens.

This is a useful quota-extension pattern for audits, planning, and focused
contract checks. It is not yet proof for broad patch-producing development
because this round stayed read-only and did not measure a same-task Codex-only
baseline.

## Observations

- `token_ledger.json` records `task_status=VERIFYING` because the ledger is
  written before final terminal status. The DB, metrics, and outcome records are
  correct, but the ledger snapshot can confuse report scripts. A follow-up
  should refresh or annotate the ledger after completion.
- Adapter-reported cost remains much higher than backend token-price
  calculation. Console/reporting should keep both values labeled until the
  adapter-cost semantics are fully understood.
- `code_contract_audit` remains the slowest profile in this sample. Seed
  evidence is sufficient for completion, but duration and cache-read volume are
  still the main optimization target.

## Recommended Next Step

Implement two small improvements before a larger confirmation run:

1. Refresh `token_ledger.json` after terminal status so task status in reports
   matches DB/outcome state.
2. Add a `turns_over_profile_budget` warning for successful tasks, starting
   with `code_contract_audit`, so success does not hide over-budget exploration.

After those two changes, run an 8-task confirmation sample:

- 2 `quick_triage`
- 2 `code_contract_audit`
- 2 `docs_review`
- 2 `next_task_planning`

Acceptance target:

- 8/8 completed or partial-completed;
- 0 `silent_max_turns_no_output`;
- 0 business repo changed files;
- average turns at or below the current 9.0-turn small-sample level;
- ledger terminal status matches the final DB status.
