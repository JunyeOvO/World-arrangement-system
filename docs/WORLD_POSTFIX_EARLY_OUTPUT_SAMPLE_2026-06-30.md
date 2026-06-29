# World Post-Fix Early-Output Sample

Date: 2026-06-30

Scope: small real validation after generalizing the `next_task_planning` early-output discipline to `quick_triage`, `code_contract_audit`, and `docs_review`.

Project under test: `travel_with_me`

## Sample Design

The sample reused the same 8-task shape as the previous post-fix run:

- 2 `quick_triage`
- 2 `code_contract_audit`
- 1 `docs_review`
- 3 `next_task_planning`
- 2 replay baseline recordings on completed tasks

All worker tasks used:

- `task_mode=read_only`
- `expected_diff=false`
- `verification_policy=none`
- `worker=claude_code`
- `model=deepseek_pro`

## Summary

| Metric | Previous Small Sample | This Sample |
| --- | ---: | ---: |
| Worker tasks | 8 | 8 |
| Completed | 5 | 6 |
| Failed | 3 | 2 |
| Success rate | 62.5% | 75.0% |
| Adapter-reported worker cost | $2.896674 | $3.464988 |
| Backend calculated worker cost | $0.161759 | $0.189974 |
| Total duration | 377219 ms | 352254 ms |
| Average duration | 47152 ms | 44032 ms |
| Worker turns | 56 | 62 |
| Worker input tokens | 313750 | 366862 |
| Worker output tokens | 24675 | 28950 |
| Worker cache-read tokens | 1051008 | 1435136 |
| Estimated Codex planning/review tokens | 3006 | 3216 |

The early-output profile change improved completion rate from 5/8 to 6/8, but did not meet the intended 7/8 acceptance bar.

## Task Results

| # | Name | Profile | Task ID | Status | Strategy Seen | Turns | Duration | Adapter Cost | Failure |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | read_config_health | quick_triage | `t_20260630_074615_741bdf` | FAILED_FINAL | quick | 7 | 22921 ms | $0.29 | max_turns_no_diff |
| 2 | read_readme_quality | docs_review | `t_20260630_074641_8548b5` | COMPLETED_WITH_ARTIFACTS | docs | 12 | 61132 ms | $0.57 |  |
| 3 | read_test_command_contract | code_contract_audit | `t_20260630_074740_288537` | COMPLETED_WITH_ARTIFACTS | contract | 8 | 30602 ms | $0.32 |  |
| 4 | read_area_contract | code_contract_audit | `t_20260630_074813_917687` | FAILED_FINAL | contract | 11 | 57095 ms | $0.66 | max_turns_no_diff |
| 5 | read_frontend_state | quick_triage | `t_20260630_074909_4d5ca0` | COMPLETED_WITH_ARTIFACTS | quick | 9 | 44707 ms | $0.46 |  |
| 6 | plan_candidate_one | next_task_planning | `t_20260630_074953_9228a8` | COMPLETED_WITH_ARTIFACTS | next | 7 | 46736 ms | $0.44 |  |
| 7 | plan_candidate_two | next_task_planning | `t_20260630_075040_2050f7` | COMPLETED_WITH_ARTIFACTS | next | 4 | 40745 ms | $0.33 |  |
| 8 | plan_candidate_three | next_task_planning | `t_20260630_075121_c382e5` | COMPLETED_WITH_ARTIFACTS | next | 4 | 48316 ms | $0.38 |  |

## What Improved

### Profile Strategy Injection

All tasks saw the intended profile strategy in `worker/prompt.md`:

- `quick_triage` tasks saw `Quick-triage early-output strategy`.
- `code_contract_audit` tasks saw `Code-contract audit early-output strategy`.
- `docs_review` saw `Docs-review early-output strategy`.
- `next_task_planning` retained its existing strategy.

This confirms the routing and prompt injection layer is working.

### Completion Rate

The sample improved from 5/8 to 6/8. The recovered task category was `quick_triage`: `read_frontend_state` completed in this run, where a similar frontend-state task failed in the previous sample.

### Baseline Filtering

2 replay baselines were recorded:

| Task | Baseline Tokens | World Codex Tokens | Estimated Codex Saved |
| --- | ---: | ---: | ---: |
| `t_20260630_074641_8548b5` | 11441 | 440 | 11001 |
| `t_20260630_074953_9228a8` | 8580 | 454 | 8126 |

Both baselines kept only stable artifacts:

```text
final.md, metrics.json, outcome.json, result.json, review/review.json,
route.json, task.json, token_ledger.json, verify/verify.json
```

The runtime artifact noise fix remains effective.

## Remaining Failures

Both failures were `max_turns_no_diff`.

### `read_config_health`

Task: `t_20260630_074615_741bdf`

Worker stream:

- `error_max_turns`
- no assistant text content before failure

This was not a partial-salvage miss. There was no structured observation to salvage.

### `read_area_contract`

Task: `t_20260630_074813_917687`

Worker stream showed the worker was close to producing a result but continued reading:

```text
Found the key files. Let me inspect the most likely contract-bearing sources...
Good. Now let me find the consumers...
Let me quickly verify the constants...
I have enough data to compile the contract audit. Let me verify one more detail...
```

This is the clearest remaining defect: the prompt says to draft after 3 files, but the worker still used later turns for more file reads.

## Assessment

The profile-specific early-output prompts helped, but prompt text alone is not a strong enough control mechanism.

The system is now acceptable for `next_task_planning` and some docs/triage tasks, but bounded code-contract audits still need a harder output protocol before the system can reliably extend Codex quota.

## Next Fix

Upgrade early output from guidance to a hard worker contract:

1. Put a required result template before exploratory instructions in the worker prompt.
2. Require the worker to write a provisional `summary` block after the first 2-3 file reads.
3. Add explicit last-turn guard text: "If this is the last allowed turn, return the template now; do not read another file."
4. Add scheduler-side detection for streams that contain phrases like "I have enough data" followed by `error_max_turns`; classify them as `worker_ignored_early_output`.
5. Consider pre-seeding `quick_triage` and `code_contract_audit` with selected file paths/evidence, not only `next_task_planning`.

Recommended next acceptance:

- 7/8 completed or partial-completed.
- 0 failures after a stream contains "I have enough data" or equivalent.
- No read-only task exceeds its `max_worker_turns` by more than one reported stream turn.
