# World Post-Fix Hard-Contract Sample

Date: 2026-06-30

Scope: real small-sample validation after adding a required read-only output template and last-turn guard to worker prompts.

Project under test: `travel_with_me`

## Fixes Validated

Before this run, World added:

- a required read-only output template in worker prompts;
- profile-specific template fields for `quick_triage`, `code_contract_audit`, `docs_review`, and `next_task_planning`;
- explicit last-turn guard language: do not spend the final allowed turn on another file read/list/search;
- failure classification for `worker_ignored_early_output` when a worker says it has enough data but still times out.

Unit/regression verification before the sample:

```text
uv run pytest
373 passed
```

## Summary

| Metric | Early-Output Sample | Hard-Contract Sample |
| --- | ---: | ---: |
| Worker tasks | 8 | 8 |
| Completed | 6 | 6 |
| Failed | 2 | 2 |
| Success rate | 75.0% | 75.0% |
| Adapter-reported worker cost | $3.464988 | $3.129699 |
| Backend calculated worker cost | $0.189974 | $0.176664 |
| Total duration | 352254 ms | 390689 ms |
| Average duration | 44032 ms | 48836 ms |
| Worker turns | 62 | 59 |
| Worker input tokens | 366862 | 348516 |
| Worker output tokens | 28950 | 23706 |
| Worker cache-read tokens | 1435136 | 1223808 |
| Estimated Codex planning/review tokens | 3216 | 3216 |

The hard prompt contract did not improve the success rate beyond the prior 6/8 result.

## Task Results

| # | Name | Profile | Task ID | Status | Template Seen | Turns | Duration | Adapter Cost | Failure |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | read_config_health | quick_triage | `t_20260630_120324_a9ef81` | FAILED_FINAL | yes | 7 | 52769 ms | $0.373839 | max_turns_no_diff |
| 2 | read_readme_quality | docs_review | `t_20260630_120416_82a452` | COMPLETED_WITH_ARTIFACTS | yes | 8 | 46637 ms | $0.384464 |  |
| 3 | read_test_command_contract | code_contract_audit | `t_20260630_120502_6ac0d5` | COMPLETED_WITH_ARTIFACTS | yes | 8 | 60708 ms | $0.376840 |  |
| 4 | read_area_contract | code_contract_audit | `t_20260630_120602_a501fc` | FAILED_FINAL | yes | 11 | 44150 ms | $0.527030 | max_turns_no_diff |
| 5 | read_frontend_state | quick_triage | `t_20260630_120646_738862` | COMPLETED_WITH_ARTIFACTS | yes | 9 | 45909 ms | $0.490200 |  |
| 6 | plan_candidate_one | next_task_planning | `t_20260630_120731_6b1fd8` | COMPLETED_WITH_ARTIFACTS | yes | 6 | 42178 ms | $0.325997 |  |
| 7 | plan_candidate_two | next_task_planning | `t_20260630_120814_d20c13` | COMPLETED_WITH_ARTIFACTS | yes | 4 | 52510 ms | $0.321108 |  |
| 8 | plan_candidate_three | next_task_planning | `t_20260630_120905_c204b2` | COMPLETED_WITH_ARTIFACTS | yes | 6 | 45828 ms | $0.330221 |  |

## Baseline Checks

2 replay baselines were recorded:

| Task | Baseline Tokens | World Codex Tokens | Estimated Codex Saved |
| --- | ---: | ---: | ---: |
| `t_20260630_120416_82a452` | 8485 | 443 | 8042 |
| `t_20260630_120731_6b1fd8` | 7231 | 451 | 6780 |

Baseline metadata remained filtered to stable artifacts only:

```text
final.md, metrics.json, outcome.json, result.json, review/review.json,
route.json, task.json, token_ledger.json, verify/verify.json
```

## Failure Analysis

Both failed tasks had the hard output contract in `worker/prompt.md`.

### `read_config_health`

Task: `t_20260630_120324_a9ef81`

Observed stream:

- `error_max_turns`
- `num_turns=7`
- no assistant text content before failure

This is not salvageable by output parsing because the worker produced no natural-language observation.

### `read_area_contract`

Task: `t_20260630_120602_a501fc`

Observed stream:

- `error_max_turns`
- `num_turns=11`
- no assistant text content before failure

Unlike the previous run, this did not trigger `worker_ignored_early_output` because there was no "I have enough data" marker in assistant text. The worker appears to have spent turns in tool/system events without yielding a summary.

## Assessment

This run proves that prompt-only control has reached its limit for these profiles.

What is working:

- Read-only routing remains correct.
- `next_task_planning` remains stable.
- `docs_review` works.
- baseline filtering remains fixed.
- hard output templates are present in all prompts.

What is not working:

- `quick_triage` and `code_contract_audit` can still spend all turns before producing any assistant text.
- The scheduler can only salvage text that exists; it cannot recover from silent tool-loop exhaustion.

## Next Fix

Move from prompt-only control to executor-level control:

1. Pre-seed `quick_triage` and `code_contract_audit` with selected file paths and small excerpts, similar to `next_task_planning`.
2. Reduce the need for worker search/list tools on these profiles.
3. Add a strict `max_tool_calls_before_summary` policy in the prompt and, if possible, in the worker adapter.
4. For read-only tasks, consider a local deterministic fallback summary when the stream has no assistant text but route/project/task metadata is enough to produce a minimal result.
5. Track `silent_max_turns_no_output` separately from ordinary `max_turns_no_diff`.

Recommended next acceptance:

- 7/8 completed or partial-completed.
- 0 silent `max_turns_no_diff` failures.
- `quick_triage` and `code_contract_audit` prompts include seed evidence, not only instructions.
