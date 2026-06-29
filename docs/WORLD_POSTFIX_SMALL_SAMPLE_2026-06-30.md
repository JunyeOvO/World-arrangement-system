# World Post-Fix Small Sample

Date: 2026-06-30

Scope: small real validation after the read-only routing, partial-result salvage, and replay-baseline filtering fixes.

Project under test: `travel_with_me`

## Sample Design

The sample focused on the previous failure modes instead of broad scanning:

- 5 read-only project analysis tasks with fix/config/docs/state keywords.
- 3 `next_task_planning` tasks with one-candidate output requirements.
- 2 replay baseline recordings on completed tasks.

All worker tasks used:

- `task_mode=read_only`
- `expected_diff=false`
- `verification_policy=none`
- `worker=claude_code`
- `model=deepseek_pro`

## Summary

| Metric | Result |
| --- | ---: |
| Worker tasks | 8 |
| Completed | 5 |
| Failed | 3 |
| Success rate | 62.5% |
| Adapter-reported worker cost | $2.896674 |
| Backend calculated worker cost | $0.161759 |
| Total duration | 377219 ms |
| Average duration | 47152 ms |
| Worker turns | 56 |
| Worker input tokens | 313750 |
| Worker output tokens | 24675 |
| Worker cache-read tokens | 1051008 |
| Estimated Codex planning/review tokens | 3006 |

Compared with the previous 20-sample run at 45% success, this is an improvement, but the sample is small and still not good enough for a production gate.

## Task Results

| # | Name | Profile | Task ID | Status | Shape | Turns | Duration | Adapter Cost | Failure |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | read_config_health | quick_triage | `t_20260629_235544_67018d` | FAILED_FINAL | review_only | 7 | 38810 ms | $0.328569 | max_turns_no_diff |
| 2 | read_readme_quality | docs_review | `t_20260629_235626_178961` | COMPLETED_WITH_ARTIFACTS | review_only | 9 | 76204 ms | $0.405501 |  |
| 3 | read_test_command_contract | code_contract_audit | `t_20260629_235743_0ede99` | COMPLETED_WITH_ARTIFACTS | review_only | 11 | 62736 ms | $0.384862 |  |
| 4 | read_area_contract | code_contract_audit | `t_20260629_235847_4f0988` | FAILED_FINAL | review_only | 11 | 35049 ms | $0.422615 | max_turns_no_diff |
| 5 | read_frontend_state | quick_triage | `t_20260629_235924_76ae2d` | FAILED_FINAL | review_only | 7 | 28424 ms | $0.427161 | max_turns_no_diff |
| 6 | plan_candidate_one | next_task_planning | `t_20260629_235955_e6d30a` | COMPLETED_WITH_ARTIFACTS | review_only | 4 | 63627 ms | $0.352724 |  |
| 7 | plan_candidate_two | next_task_planning | `t_20260630_000100_858a0b` | COMPLETED_WITH_ARTIFACTS | review_only | 1 | 33243 ms | $0.248475 |  |
| 8 | plan_candidate_three | next_task_planning | `t_20260630_000135_be0375` | COMPLETED_WITH_ARTIFACTS | review_only | 6 | 39126 ms | $0.326767 |  |

## What Improved

### Read-Only Routing

All 8 tasks routed as `review_only`.

This confirms the post-fix override works: goals containing words like config, fix, README, or docs no longer become patch-style task shapes when `task_mode=read_only` or `expected_diff=false`.

### Next-Task Planning

All 3 `next_task_planning` tasks completed.

The tuned strategy of limiting search and requiring an early single-candidate draft worked in this sample. One task found a concrete low-risk bug candidate in `js/route-config.js`: explicit `manual: false` can be overridden to `manual: true` when labels or legs are present.

### Replay Baseline Filtering

2 baseline records were created successfully:

| Task | Baseline Tokens | World Codex Tokens | Estimated Codex Saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| `t_20260629_235626_178961` | 9856 | 440 | 9416 | 95.54% |
| `t_20260629_235955_e6d30a` | 7475 | 451 | 7024 | 93.97% |

The baseline metadata now lists only stable artifacts:

```text
final.md, metrics.json, outcome.json, result.json, review/review.json,
route.json, task.json, token_ledger.json, verify/verify.json
```

Runtime paths were excluded and counted separately:

- `artifact_count=242`
- `excluded_runtime_artifact_count=224`

This verifies the previous worktree/worker/control noise issue is fixed.

## Remaining Failures

All 3 failures ended as `max_turns_no_diff`.

Worker stream inspection showed these were not salvage misses:

- `read_config_health`: no assistant text content in the stream before `error_max_turns`.
- `read_area_contract`: only exploratory text: "Now let me read the core contract files..."
- `read_frontend_state`: only exploratory text about reading architecture and 3D files.

The partial-result salvage correctly refused to mark these as completed because they had no structured observations, conclusion, risks, or next steps.

## Assessment

The post-fix changes are directionally effective:

- Misrouting is fixed in this sample.
- `next_task_planning` is now usable for candidate selection.
- Baseline noise is fixed.

The system is still too weak on bounded read-only audits. The worker can spend all turns reading files and fail before producing even a partial summary.

## Next Fix

Add the same early-output discipline used by `next_task_planning` to all read-only profiles:

1. `quick_triage`: after at most 2 file reads, output a provisional conclusion block.
2. `code_contract_audit`: after at most 3 file reads, output a contract hypothesis, evidence, and next file if needed.
3. `docs_review`: after at most 2 docs/files, output a partial scorecard.
4. Worker prompt should require a final JSON or markdown result before using the last allowed turn.
5. Scheduler should warn when `num_turns > max_turns` because the observed stream reports 7 turns for a 6-turn profile and 11 turns for a 10-turn profile.

Recommended acceptance for the next small run:

- At least 7 / 8 completed or partial-completed.
- 0 patch-style retry chains for read-only tasks.
- 0 baseline metadata entries under `worktrees/`, `worker/`, `control/`, or `attempts/`.

## Follow-Up Implemented

The `next_task_planning` early-output discipline has been generalized to the other read-only profiles:

- `quick_triage`: draft a provisional conclusion after at most 2 file reads.
- `code_contract_audit`: draft a contract hypothesis after at most 3 file reads, then read only to confirm or reject it.
- `docs_review`: draft a scorecard after at most 2 docs/config files.

All three profiles now explicitly tell the worker to return a partial result with `changed_files=[]` instead of spending the final turns on more exploration.
