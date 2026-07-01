# World Small Comparison Sample - 2026-07-01 Round 4

Scope: small read-only comparison sample for `travel_with_me`, run after the
Round 3 regression where `code_contract_audit` failed with
`silent_max_turns_no_output`.

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

| Metric | Round 3 4-task sample | Round 4 4-task sample |
| --- | ---: | ---: |
| Worker tasks | 4 | 4 |
| Full completed | 3 | 3 |
| Partial completed | 0 | 1 |
| Failed | 1 | 0 |
| Usable completion rate | 75.0% | 100.0% |
| Verified quality outcomes | 3 | 4 |
| Accepted outcomes | 3 | 4 |
| Adapter-reported worker cost | $2.340811 | $2.044560 |
| Backend calculated worker cost | $0.039284 | $0.035095 |
| Total duration | 264332 ms | 244528 ms |
| Average duration | 66083 ms | 61132 ms |
| Worker turns | 50 | 38 |
| Average worker turns | 12.50 | 9.50 |
| Worker input tokens | 211212 | 190337 |
| Worker output tokens | 22260 | 20809 |
| Worker cache-read tokens | 1243392 | 936320 |
| Estimated Codex planning/review tokens | 1678 | 2005 |
| `silent_max_turns_no_output` failures | 1 | 0 |
| Business repo changed files | 0 | 0 |

Round 4 passed the immediate small-sample gate. The previous hard failure was
removed: `code_contract_audit` completed with a usable final result, and the
sample had zero `silent_max_turns_no_output` failures. The tradeoff is that
`docs_review` still hit `error_max_turns`, but the read-only partial-result
salvage path converted it into `COMPLETED_WITH_PARTIAL_ARTIFACTS` with a
verified and accepted outcome.

## Task Matrix

| # | Name | Profile | Task ID | Status | Quality | Turns | Duration | Adapter Cost | Backend Cost | Input | Output | Cache read | Codex est. |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `quick_runtime_entrypoint_recheck` | `quick_triage` | `t_20260701_015831_62617a` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 6 | 23882 ms | $0.284536 | $0.005384 | 32869 | 1836 | 95872 | 502 |
| 2 | `workarea_contract_executor_check` | `code_contract_audit` | `t_20260701_015858_0a339a` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 13 | 97860 ms | $0.808593 | $0.013590 | 71223 | 8889 | 403456 | 502 |
| 3 | `docs_command_consistency_recheck` | `docs_review` | `t_20260701_020034_fa6ac3` | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | verified / accepted | 7 | 43396 ms | $0.435122 | $0.007956 | 45764 | 3527 | 200704 | 503 |
| 4 | `next_small_quality_task_candidate` | `next_task_planning` | `t_20260701_020120_548219` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 12 | 79390 ms | $0.516309 | $0.008165 | 40481 | 6557 | 236288 | 498 |

## Validation Evidence

- `detect-project --repo-path C:\Users\fujunye\Desktop\Agent\travel_with_me`
  returned `project_id=travel_with_me`, confidence `1.0`, and health `ok`.
- `git -C C:\Users\fujunye\Desktop\Agent\travel_with_me status --short --branch`
  was clean after the sample.
- Every task reported `changed_files_count=0`.
- Completed and partial-completed tasks produced `final.md`, `metrics.json`,
  `outcome.json`, `token_ledger.json`, and `verify/verify.json`.
- The `docs_review` task recorded `failure_reason=error_max_turns`, but the
  read-only salvage path produced a verified partial artifact instead of a
  failed final state.

## Findings From Worker Outputs

1. `quick_triage` found the runtime entrypoints mostly coherent, but flagged
   `playwright.config.js` using `npm.cmd start`, which is Windows-specific and
   can fail under WSL/Linux execution.
2. `code_contract_audit` completed this round. It found the `workArea` data
   contract coherent across `toggle-3d.js`, `three-work-area.js`, `map-3d.js`,
   and `main.js`. The main risk is that `workArea.profile` is currently a
   passenger field and does not directly drive terrain/camera behavior.
3. `docs_review` found real onboarding drift: README test counts are stale,
   CI command coverage differs from the documented `check` flow, and Node
   version guidance is inconsistent. This result was salvaged from a worker
   budget limit, so it is useful but not a fully structured scorecard.
4. `next_task_planning` produced one concrete candidate: fix
   `js/render/route-editor-modal.js` so saving a route preserves existing
   `geometry`, `legs`, and `label`, then add a unit test for that behavior.

## Codex Workload Assessment

This round still supports the quota-saving hypothesis for bounded read-only
World tasks, with an important caveat that Codex-only baselines are still not
measured for the same tasks.

- Worker-side real token use: 190337 input, 20809 output, 936320 cache-read.
- Codex-side estimated planning/review tokens: 2005.
- Approximate Codex share of counted tokens: about 0.17% when cache-read tokens
  are included, or about 0.94% using only worker input+output plus Codex
  estimated tokens.
- Backend calculated worker cost: $0.035095.

The practical result improved because all four tasks returned usable artifacts.
The system still needs tighter control for profiles that can exceed their turn
budget while producing useful evidence.

## Remaining Issues

1. `docs_review` still reached `error_max_turns`. Partial salvage prevented a
   hard failure, but the executor should force the structured scorecard earlier.
2. `code_contract_audit` succeeded but used 13 turns against a 10-turn profile
   target, so over-budget success is still hidden unless the report is reviewed.
3. `quick_triage` returned `partial: true` inside the worker text even though
   the task was recorded as a full artifact completion. The parser should expose
   this distinction as a warning.
4. `token_ledger.json` still records `task_status=VERIFYING` in the snapshot,
   even when final task status is terminal.

## Next Step

The next engineering improvement should be a quality-warning layer rather than
more budget:

- Record `turns_over_profile_budget` when `num_turns` exceeds the configured
  `max_worker_turns`.
- Parse `partial: true` from read-only worker output and record it as
  `worker_declared_partial`.
- Force `docs_review` to emit the scorecard template before its final allowed
  turn.
- Refresh token ledger after terminal status so `task_status` matches the final
  DB status.

After those fixes, run a 6-task confirmation sample:

- 2 `quick_triage`
- 2 `code_contract_audit`
- 1 `docs_review`
- 1 `next_task_planning`

Acceptance target:

- 6/6 usable completions;
- 0 `silent_max_turns_no_output`;
- 0 business repo changed files;
- no hidden over-budget success without a quality warning;
- terminal status in `token_ledger.json` matches final task status.
