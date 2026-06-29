# World 20-Sample Real Validation Report - 2026-06-29

Project: `travel_with_me`  
Mode: real World worker execution, read-only, zero business-repo writes  
Protocol: `task_mode=read_only`, `expected_diff=false`, `verification_policy=changed_files_only`  
Profiles tested: `quick_triage`, `code_contract_audit`, `docs_review`, `next_task_planning`

## Executive Result

This 20-sample validation **does not pass** the production-readiness gate.

World stayed inside the safety boundary, but task success was too low:

- Samples: 20
- Success: 9
- Failed: 11
- Success rate: 45.0%
- Rework required: 11 / 20
- Business repo changed files: 0
- Project verification commands executed: 0
- Total worker cost: `$9.7596`
- Average duration: `73.8s`
- Worker turns: 229
- Worker input tokens: 1,624,636
- Worker output tokens: 68,732
- Worker cache-read input tokens: 6,382,809

The core failure mode was consistent: most failed tasks hit
`max_turns_no_diff` or `worker_no_diff`. In plain terms, the worker consumed the
read budget but did not produce a final artifact, so World correctly marked the
task failed.

## Codex Quota Evidence

Replay baselines were recorded for all 20 tasks.

- Replay baseline total: 142,874 tokens
- World Codex planning/review total: 6,984 tokens
- Replay-estimated Codex reduction: 135,890 tokens, about 95.1%

This is useful trend evidence, but it is **not strong enough** to claim that
World extends Codex quota from two days to one week.

Reasons:

- The baselines are replay estimates, not measured same-task Codex-only runs.
- The current replay baseline includes large artifact/worktree path indexes,
  which likely inflates the counterfactual Codex-only token estimate.
- Worker cost and failure rate are too high for the current protocol.
- Failed tasks still require Codex attention, so they do not fully save Codex
  work even if planning/review tokens are low.

## Profile Results

| Profile | Tasks | Success | Success rate | Cost | Avg duration |
|---|---:|---:|---:|---:|---:|
| `quick_triage` | 6 | 4 | 66.67% | $2.5236 | 73.7s |
| `code_contract_audit` | 6 | 1 | 16.67% | $3.5415 | 81.8s |
| `docs_review` | 6 | 2 | 33.33% | $2.9588 | 68.3s |
| `next_task_planning` | 2 | 2 | 100.0% | $0.7356 | 66.2s |

The only clearly good profile in this run was `next_task_planning`.
`code_contract_audit` and `docs_review` are not reliable under their current
budget and prompt protocol.

## Sample Matrix

| # | Sample | Profile | Task ID | Status | Shape | Budget | Cost | Duration | Turns | Quality | Failure |
|---:|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 1 | stack_entrypoints | quick_triage | `t_20260629_213025_a91136` | COMPLETED_WITH_ARTIFACTS | targeted_patch | 6 / 90s | $0.3260 | 39.4s | 12 | verified |  |
| 2 | test_gate_minimal | quick_triage | `t_20260629_213109_71de3e` | COMPLETED_WITH_ARTIFACTS | config_repair | 6 / 90s | $0.3201 | 47.1s | 9 | verified |  |
| 3 | selected_workarea_contract | code_contract_audit | `t_20260629_213158_ae7ee9` | FAILED_FINAL | review_only | 10 / 150s | $0.5907 | 49.1s | 11 | failed | max_turns_no_diff |
| 4 | three_scene_assets | code_contract_audit | `t_20260629_213249_e4f554` | FAILED_FINAL | targeted_patch | 10 / 150s | $0.9924 | 194.2s | 22 | failed | max_turns_no_diff |
| 5 | amap_boundary | code_contract_audit | `t_20260629_213652_0392b9` | COMPLETED_WITH_ARTIFACTS | targeted_patch | 10 / 150s | $0.6908 | 91.5s | 19 | verified |  |
| 6 | state_sync | code_contract_audit | `t_20260629_213825_8ff07d` | FAILED_FINAL | targeted_patch | 10 / 150s | $0.5996 | 71.4s | 13 | failed | max_turns_no_diff |
| 7 | unit_test_candidates | docs_review | `t_20260629_214153_6ce7d3` | FAILED_FINAL | targeted_patch | 6 / 90s | $0.4849 | 110.3s | 16 | failed | max_turns_no_diff |
| 8 | e2e_smoke_scope | docs_review | `t_20260629_214401_63023c` | FAILED_FINAL | targeted_patch | 6 / 90s | $0.3258 | 29.1s | 7 | failed | max_turns_no_diff |
| 9 | readme_gaps | docs_review | `t_20260629_214604_0f852b` | FAILED_FINAL | docs_update | 6 / 90s | $0.9263 | 109.4s | 14 | failed | max_turns_no_diff |
| 10 | dependency_risk | quick_triage | `t_20260629_214757_0a9f6f` | FAILED_FINAL | config_repair | 6 / 90s | $0.3333 | 39.7s | 7 | failed | max_turns_no_diff |
| 11 | api_shape_review | code_contract_audit | `t_20260629_215010_67ac5d` | FAILED_FINAL | review_only | 10 / 150s | $0.0000 | 0.0s | 0 | failed | worker_no_diff |
| 12 | error_empty_state | code_contract_audit | `t_20260629_215243_80fd59` | FAILED_FINAL | targeted_patch | 10 / 150s | $0.6680 | 84.5s | 18 | failed | max_turns_no_diff |
| 13 | performance_hotspots | quick_triage | `t_20260629_215620_1d5ffc` | FAILED_FINAL | targeted_patch | 6 / 90s | $0.4883 | 119.9s | 25 | failed | max_turns_no_diff |
| 14 | security_surface | quick_triage | `t_20260629_215830_dff8a4` | COMPLETED_WITH_ARTIFACTS | config_repair | 6 / 90s | $0.5952 | 121.0s | 12 | verified |  |
| 15 | patch_candidate_one | next_task_planning | `t_20260629_220047_b44e35` | COMPLETED_WITH_ARTIFACTS | review_only | 14 / 210s | $0.4455 | 80.1s | 10 | verified |  |
| 16 | patch_candidate_two | next_task_planning | `t_20260629_220210_53af44` | COMPLETED_WITH_ARTIFACTS | review_only | 14 / 210s | $0.2901 | 52.2s | 4 | verified |  |
| 17 | playwright_gap | docs_review | `t_20260629_220304_baa7e5` | COMPLETED_WITH_ARTIFACTS | targeted_patch | 6 / 90s | $0.4879 | 63.3s | 9 | verified |  |
| 18 | vitest_gap | docs_review | `t_20260629_220410_129f3b` | FAILED_FINAL | targeted_patch | 6 / 90s | $0.3249 | 31.6s | 7 | failed | max_turns_no_diff |
| 19 | release_readiness | quick_triage | `t_20260629_220616_cd282f` | COMPLETED_WITH_ARTIFACTS | targeted_patch | 6 / 90s | $0.4608 | 75.2s | 8 | verified |  |
| 20 | world_fit_assessment | docs_review | `t_20260629_220736_e1e2e4` | COMPLETED_WITH_ARTIFACTS | review_only | 6 / 90s | $0.4090 | 66.1s | 6 | verified |  |

## What Worked

- Safety boundary held: no business-repo writes.
- Verification boundary held: no accidental project test/build commands.
- Task outcomes and baselines were recorded.
- `next_task_planning` succeeded 2 / 2 after its recent strategy tuning.
- The Console will now have enough outcome, token, cost, and baseline evidence
  to display this run.

## What Failed

### 1. Router/task-shape classification is too write-biased

Many explicitly read-only tasks were classified as `targeted_patch`,
`config_repair`, or `docs_update` because words like "check", "test",
"README", "config", or "risk" trigger implementation-oriented shapes.

For read-only requests, `task_mode=read_only` should dominate task-shape
classification. A read-only task should usually route as:

- `review_only`
- `docs_review`
- `contract_audit`
- `triage`

It should not become `targeted_patch` unless `expected_diff=true`.

### 2. Budget exhaustion currently becomes failure instead of partial answer

For many tasks the worker read useful context, but once it hit max turns without
a diff/final artifact, World marked the whole task `FAILED_FINAL`.

For read-only tasks, this should become:

- `COMPLETED_WITH_PARTIAL_ARTIFACTS` if any structured observations exist, or
- `NEEDS_USER` with a narrow continuation prompt if no answer was produced.

It should not count like a failed patch.

### 3. docs_review budget is too small and prompt is too broad

`docs_review` with 6 turns / 90 seconds failed 4 / 6. The successful cases were
either narrow or had clearer output constraints.

### 4. code_contract_audit needs a forced one-pass output protocol

`code_contract_audit` failed 5 / 6. It likely needs:

- fewer candidate files,
- one primary data-flow path only,
- "after N files, output the best current diagnosis",
- no open-ended exploration.

### 5. Replay baseline needs correction

Replay baseline should not include full worktree artifact indexes. That inflates
baseline tokens and makes Codex-savings percentages look stronger than they are.

## Decision

World currently helps with narrow read-only planning and some quick triage, but
this run shows it is **not yet reliable enough** to broadly offload real project
analysis without Codex supervision.

The system is still useful, but the next optimization should focus on reliability
before more feature expansion.

## Required Fixes Before Next 20-Sample Run

1. Make `task_mode=read_only` override implementation-oriented task shapes.
2. Add `COMPLETED_WITH_PARTIAL_ARTIFACTS` or equivalent partial-success handling
   for read-only max-turn cases with useful observations.
3. Force read-only worker prompts to emit a draft after the first candidate path.
4. Tighten `code_contract_audit` to one data-flow path and one suspected root
   cause by default.
5. Increase `docs_review` budget slightly or narrow its prompt template.
6. Fix replay baseline so it excludes worktree path indexes and runtime noise.

## Next Acceptance Gate

Run another 20-sample after the fixes with the same categories.

Minimum pass criteria:

- Success rate >= 85%
- Rework required <= 15%
- Total worker cost <= $7.00
- Average duration <= 65s
- No business-repo writes
- No accidental verification commands for read-only tasks
- Replay baseline corrected, or at least 5 actual Codex-only baselines recorded

Until then, any claim that World reliably extends Codex weekly quota should be
phrased as "promising but unproven."
