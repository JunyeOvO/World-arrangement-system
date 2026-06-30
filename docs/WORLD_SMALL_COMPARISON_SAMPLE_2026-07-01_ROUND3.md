# World Small Comparison Sample - 2026-07-01 Round 3

Scope: small read-only comparison sample for `travel_with_me`, run after the
executor-level seed evidence and early-output controls were extended to
`quick_triage`, `code_contract_audit`, and `docs_review`.

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

| Metric | Round 2 4-task sample | Round 3 4-task sample |
| --- | ---: | ---: |
| Worker tasks | 4 | 4 |
| Completed | 4 | 3 |
| Failed | 0 | 1 |
| Success rate | 100.0% | 75.0% |
| Verified quality outcomes | 4 | 3 |
| Accepted outcomes | 4 | 3 |
| Adapter-reported worker cost | $2.025572 | $2.340811 |
| Backend calculated worker cost | $0.035829 | $0.039284 |
| Total duration | 259318 ms | 264332 ms |
| Average duration | 64830 ms | 66083 ms |
| Worker turns | 36 | 50 |
| Average worker turns | 9.00 | 12.50 |
| Worker input tokens | 195911 | 211212 |
| Worker output tokens | 22327 | 22260 |
| Worker cache-read tokens | 767744 | 1243392 |
| Estimated Codex planning/review tokens | 1831 | 1678 |
| `silent_max_turns_no_output` failures | 0 | 1 |
| Business repo changed files | 0 | 0 |

Round 3 regressed versus Round 2. The system still works for quick triage,
docs review, and next-task planning, but `code_contract_audit` remains unstable
under the current 10-turn cap. The failed task produced useful internal
analysis in the worker stream, but it did not emit the required final result
before hitting `error_max_turns`; therefore World correctly recorded
`silent_max_turns_no_output` and marked the task `FAILED_FINAL`.

## Task Matrix

| # | Name | Profile | Task ID | Status | Quality | Turns | Duration | Adapter Cost | Backend Cost | Input | Output | Cache read | Codex est. |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `runtime_health_after_refactor` | `quick_triage` | `t_20260701_013022_55ab79` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 10 | 30845 ms | $0.377108 | $0.007375 | 45351 | 2463 | 119936 | 471 |
| 2 | `workarea_contract_seeded_audit` | `code_contract_audit` | `t_20260701_013056_9b3baa` | `FAILED_FINAL` | failed / rejected | 11 | 57097 ms | $0.519985 | $0.008021 | 41619 | 4459 | 337920 | 285 |
| 3 | `docs_test_commands_recheck` | `docs_review` | `t_20260701_013154_cfa81e` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 8 | 30756 ms | $0.406558 | $0.008554 | 53755 | 2587 | 108416 | 457 |
| 4 | `next_visual_gate_candidate` | `next_task_planning` | `t_20260701_013227_66b9d4` | `COMPLETED_WITH_ARTIFACTS` | verified / accepted | 21 | 145634 ms | $1.037160 | $0.015334 | 70487 | 12751 | 677120 | 465 |

## Validation Evidence

- `detect-project --repo-path C:\Users\fujunye\Desktop\Agent\travel_with_me`
  returned `project_id=travel_with_me`, confidence `1.0`, and health `ok`.
- `git -C C:\Users\fujunye\Desktop\Agent\travel_with_me status --short --branch`
  was clean after the sample.
- Completed tasks produced `final.md`, `metrics.json`, `outcome.json`,
  `token_ledger.json`, and `verify/verify.json`.
- The failed `code_contract_audit` task produced `metrics.json`,
  `outcome.json`, `result.json`, and `token_ledger.json`, but no `final.md`
  and no `verify/verify.json`.
- Every task reported `changed_files_count=0`.

## Findings From Worker Outputs

1. `quick_triage` found the start/test/check entrypoints coherent. It still
   recommended running `npm run check` and `npm test` before merge, but found no
   structural script mismatch.
2. `docs_review` found real documentation drift: README test count and
   `npm run check` description are stale, and
   `docs/development-workflow-foundation.md` still describes Playwright as
   future work even though it is already installed and used.
3. `next_task_planning` produced one bounded candidate: add `scenic-park` to
   `OVERVIEW_INSPECT_REVIEW_SCENES` in
   `tests/e2e/visual-baseline.spec.js` and verify with visual + unit tests.
4. `code_contract_audit` failed because the worker continued analysis and tool
   use until the 10-turn cap. The stream contains a draft conclusion about
   duplicated/implicit workArea normalization, but the worker did not emit the
   required final response before `error_max_turns`.

## Codex Workload Assessment

This round still shows low Codex-side orchestration cost for completed tasks,
but the failed `code_contract_audit` reduces the practical savings:

- Worker-side real token use: 211212 input, 22260 output, 1243392 cache-read.
- Codex-side estimated planning/review tokens: 1678.
- Approximate Codex share of counted tokens: about 0.11% when cache-read tokens
  are included, or about 0.71% using only worker input+output plus Codex tokens.

The quota-saving pattern remains valid for bounded read-only tasks that finish.
For `code_contract_audit`, failed work still consumes worker tokens and returns
no usable artifact, so it does not reliably save Codex review time until the
executor can salvage the draft conclusion or force earlier final emission.

## Required Follow-Up

1. Fix `code_contract_audit` at the executor boundary, not by increasing budget:
   enforce "one evidence pass, one risk, emit final before optional extra reads".
2. Add partial-result salvage for read-only failures where the stream contains
   a substantial draft analysis but no final artifact.
3. Refresh `token_ledger.json` after terminal status. Round 3 still records
   terminal tasks as `VERIFYING` or `EXECUTING` inside the ledger snapshot.
4. Add a warning when successful tasks exceed their profile turn budget. The
   `next_task_planning` task succeeded but used 21 turns, above the intended
   profile cap.

## Next Confirmation Gate

Run another 4-task sample only after the above fixes:

- 1 `quick_triage`
- 1 `code_contract_audit`
- 1 `docs_review`
- 1 `next_task_planning`

Acceptance target:

- 4/4 completed or partial-completed;
- 0 `silent_max_turns_no_output`;
- 0 business repo changed files;
- average turns at or below 9.0;
- ledger task status matches final DB status.
