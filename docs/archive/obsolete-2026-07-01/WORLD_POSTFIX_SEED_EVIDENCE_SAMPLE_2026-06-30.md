# World Post-Fix Seed Evidence Sample

Date: 2026-06-30

Scope: small real validation after adding executor-side seed evidence to `quick_triage` and `code_contract_audit`, plus the `silent_max_turns_no_output` failure classification.

Project under test: `travel_with_me`

## Summary

| Metric | Hard-Contract Sample | Seed-Evidence Sample |
| --- | ---: | ---: |
| Worker tasks | 8 | 8 |
| Completed | 6 | 8 |
| Failed | 2 | 0 |
| Success rate | 75.0% | 100.0% |
| Adapter-reported worker cost | $3.129699 | $3.318685 |
| Backend calculated worker cost | $0.176664 | $0.183878 |
| Total duration | 390689 ms | 529573 ms |
| Average duration | 48836 ms | 66197 ms |
| Worker turns | 59 | 58 |
| Worker input tokens | 348516 | 352529 |
| Worker output tokens | 23706 | 30329 |
| Worker cache-read tokens | 1223808 | 1142400 |
| Estimated Codex planning/review tokens | 3216 | 3588 |

The seed-evidence change met the target acceptance bar: 8/8 completed, with no `max_turns_no_diff` or `silent_max_turns_no_output` failures.

## Task Results

| # | Name | Profile | Task ID | Status | Seed | Turns | Duration | Adapter Cost | Backend Cost |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 | read_config_health | quick_triage | `t_20260630_133708_172d77` | COMPLETED_WITH_ARTIFACTS | quick | 7 | 49993 ms | $0.35 | $0.02 |
| 2 | read_readme_quality | docs_review | `t_20260630_133758_4105a2` | COMPLETED_WITH_ARTIFACTS | docs | 10 | 56385 ms | $0.39 | $0.02 |
| 3 | read_test_command_contract | code_contract_audit | `t_20260630_133854_f4b1b1` | COMPLETED_WITH_ARTIFACTS | contract | 11 | 58336 ms | $0.40 | $0.02 |
| 4 | read_area_contract | code_contract_audit | `t_20260630_133951_cc1e2d` | COMPLETED_WITH_ARTIFACTS | contract | 7 | 82095 ms | $0.56 | $0.03 |
| 5 | read_frontend_state | quick_triage | `t_20260630_134110_bc3bfe` | COMPLETED_WITH_ARTIFACTS | quick | 3 | 43122 ms | $0.36 | $0.02 |
| 6 | plan_candidate_one | next_task_planning | `t_20260630_134154_1e2f9e` | COMPLETED_WITH_ARTIFACTS | next | 10 | 110470 ms | $0.54 | $0.03 |
| 7 | plan_candidate_two | next_task_planning | `t_20260630_134338_17eef3` | COMPLETED_WITH_ARTIFACTS | next | 4 | 58474 ms | $0.32 | $0.02 |
| 8 | plan_candidate_three | next_task_planning | `t_20260630_134436_4151dc` | COMPLETED_WITH_ARTIFACTS | next | 6 | 70698 ms | $0.41 | $0.02 |

## What Changed

The prior hard-contract prompt still failed when workers spent all turns in tool/system events without producing assistant text. This run added executor-side seed evidence:

- `quick_triage` received selected README/package/architecture/entrypoint-style files and compact excerpts.
- `code_contract_audit` received contract-likely files such as work-area, 3D, state, route, config, tests, README, and package metadata.
- `next_task_planning` kept its existing seed evidence flow.

This reduced the need for the worker to spend early turns listing/searching the repo.

## Baseline Checks

2 replay baselines were recorded:

| Task | Baseline Tokens | World Codex Tokens | Estimated Codex Saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| `t_20260630_133708_172d77` | 7360 | 271 | 7089 | 96.32% |
| `t_20260630_133951_cc1e2d` | 9005 | 636 | 8369 | 92.94% |

Combined replay baseline:

- baseline tokens: 16365
- World Codex tokens saved: 15458
- estimated reduction: 94.46%

Baseline metadata remained limited to stable artifacts:

```text
final.md, metrics.json, outcome.json, result.json, review/review.json,
route.json, task.json, token_ledger.json, verify/verify.json
```

## Assessment

This is the first small post-fix sample that passes the read-only MVP acceptance gate.

Evidence:

- 8/8 completed.
- `quick_triage` no longer failed on config/project-health review.
- `code_contract_audit` no longer failed on selected workArea contract review.
- No silent max-turn failures.
- Baseline artifact filtering remained clean.

Residual risk:

- This is still a small sample on one project.
- Adapter-reported cost remains much higher than backend token-price calculation.
- Some successful tasks still used more reported turns than the nominal profile limit, so turn accounting should be reviewed separately.

## Recommended Next Step

Run one wider 16-task read-only validation before expanding to patch-producing tasks:

- 4 `quick_triage`
- 4 `code_contract_audit`
- 3 `docs_review`
- 3 `next_task_planning`
- 2 multimodal or UI screenshot analysis tasks if MiMo is available

Acceptance target:

- at least 14/16 completed or partial-completed;
- 0 `silent_max_turns_no_output`;
- no read-only task routed to a patch fallback chain;
- baseline metadata remains free of runtime paths.
