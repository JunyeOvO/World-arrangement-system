# World Small Comparison Sample - 2026-07-01

Scope: small real read-only comparison sample after adding executor-side seed
evidence for `quick_triage` and `code_contract_audit`, plus separate tracking
for `silent_max_turns_no_output`.

Project under test: `travel_with_me`

All tasks used:

- `worker=claude_code`
- `model=deepseek_flash`
- `task_mode=read_only`
- `expected_diff=false`
- `verification_policy=changed_files_only`
- no business repo writes

## Summary

| Metric | Previous comparable 6-task subset | This sample |
| --- | ---: | ---: |
| Worker tasks | 6 | 6 |
| Completed | 4 | 6 |
| Failed | 2 | 0 |
| Success rate | 66.7% | 100.0% |
| Verified quality outcomes | 4 | 6 |
| Accepted outcomes | 4 | 6 |
| Total metrics cost | $2.478370 | $3.098607 |
| Total duration | 292351 ms | 330398 ms |
| Average duration | 48725 ms | 55066 ms |
| Worker turns | 49 | 56 |
| Worker input tokens | unavailable | 288866 |
| Worker output tokens | unavailable | 34332 |
| Worker cache-read tokens | unavailable | 1278464 |
| `silent_max_turns_no_output` failures | not tracked separately | 0 |

The sample passed the immediate post-fix gate: the two historically weak
profiles, `quick_triage` and `code_contract_audit`, completed all selected
tasks and produced read-only artifacts.

## Task Matrix

| # | Name | Profile | Task ID | Status | Quality | Turns | Duration | Cost | Input | Output | Cache read |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `read_config_health_seeded` | `quick_triage` | `t_20260701_000738_23cf7f` | `COMPLETED_WITH_ARTIFACTS` | verified | 5 | 31633 ms | $0.299983 | 32616 | 3272 | 63616 |
| 2 | `read_frontend_state_seeded` | `quick_triage` | `t_20260701_000812_3378cc` | `COMPLETED_WITH_ARTIFACTS` | verified | 6 | 59037 ms | $0.499566 | 57425 | 5757 | 85632 |
| 3 | `read_area_contract_seeded` | `code_contract_audit` | `t_20260701_000912_84f6cd` | `COMPLETED_WITH_ARTIFACTS` | verified | 15 | 101394 ms | $0.958289 | 75148 | 11437 | 535808 |
| 4 | `read_test_command_contract_seeded` | `code_contract_audit` | `t_20260701_001054_085a01` | `COMPLETED_WITH_ARTIFACTS` | verified | 10 | 35558 ms | $0.394382 | 36314 | 3890 | 175744 |
| 5 | `read_readme_quality_seeded` | `docs_review` | `t_20260701_001132_834fb1` | `COMPLETED_WITH_ARTIFACTS` | verified | 7 | 32288 ms | $0.349642 | 39638 | 3088 | 99584 |
| 6 | `plan_candidate_seeded` | `next_task_planning` | `t_20260701_001207_34fb76` | `COMPLETED_WITH_ARTIFACTS` | verified | 13 | 70488 ms | $0.596745 | 47725 | 6888 | 318080 |

## Validation Evidence

- `detect-project --repo-path C:\Users\fujunye\Desktop\Agent\travel_with_me`
  returned `project_id=travel_with_me`, confidence `1.0`, and health `ok`.
- Worker prompts included seed-evidence blocks:
  - `Seed files World selected for quick_triage`
  - `Seed files World selected for code_contract_audit`
  - `Next-task planning strategy`
- Worker streams did not contain `error_max_turns` or
  `silent_max_turns_no_output`.
- Every task produced `final.md`, `metrics.json`, and `outcome.json`.
- Every task had `changed_files=[]`.

## Findings

Executor-side seed evidence fixed the immediate silent-failure symptom in this
small sample. The previously failing `read_config_health` and
`read_area_contract` shapes both completed.

The fix is not yet fully efficient. `read_area_contract_seeded` succeeded, but
it still used 15 turns, 101394 ms, 11437 output tokens, and 535808 cache-read
tokens. That means the worker had enough context to finish, but the
`code_contract_audit` execution budget is not yet strict enough.

The `quick_triage` profile now looks usable for bounded read-only checks. Both
quick tasks completed with 5-6 turns and no repository writes.

`next_task_planning` remained reliable, but the one-candidate strategy still
used 13 turns in this run. It should remain limited to planning tasks where a
slightly higher read budget is acceptable.

## Next Optimization

1. Add a hard adapter-side guard for read-only profiles: after N tool calls,
   force a final answer instead of only asking in the prompt.
2. Tighten `code_contract_audit` seed file selection so it excludes adjacent
   non-contract files unless the goal explicitly asks for them.
3. Track `turns_over_profile_budget` as a quality warning even when the final
   status is successful.
4. Add a compact "seed evidence was used" metric to `metrics.json` or
   `outcome.json`, so Console can distinguish prompt-only success from
   executor-seeded success.
5. Run an 8-task confirmation sample only after the turn-budget warning is
   visible in Metrics.
