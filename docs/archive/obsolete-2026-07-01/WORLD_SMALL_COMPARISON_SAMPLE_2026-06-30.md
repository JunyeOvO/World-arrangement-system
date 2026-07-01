# World Small Comparison Sample - 2026-06-30

Project under test: `travel_with_me`

Purpose: validate whether the executor-level read-only controls are improving real task completion after the previous post-fix run reached 6/8.

## Protocol

All samples used:

- `project=travel_with_me`
- `task_mode=read_only`
- `expected_diff=false`
- `verification_policy=none`
- `worker=claude_code`
- `model=deepseek_pro`
- no business-repo writes
- no auto merge or PR

Profiles covered:

- `quick_triage`
- `code_contract_audit`
- `docs_review`
- `next_task_planning`

## Result Summary

| Metric | Previous post-fix sample | This small sample |
| --- | ---: | ---: |
| Worker tasks | 8 | 4 |
| Completed | 6 | 4 |
| Failed | 2 | 0 |
| Success rate | 75.0% | 100.0% |
| Adapter-reported worker cost | $3.464988 | $1.685366 |
| Backend calculated worker cost | $0.189974 | $0.092025 |
| Total duration | 352254 ms | 212284 ms |
| Average duration | 44032 ms | 53071 ms |
| Worker turns | 62 | 26 |
| Worker input tokens | 366862 | 178642 |
| Worker output tokens | 28950 | 13578 |
| Worker cache-read tokens | 1435136 | 690432 |
| Estimated Codex planning/review tokens | 3216 | 1966 |

This is a small sample, so it should be treated as a directional check rather than a final readiness proof.

## Sample Matrix

| # | Sample | Profile | Task ID | Status | Turns | Duration | Adapter Cost | Backend Cost | Input | Output | Cache Read |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Project config health | `quick_triage` | `t_20260630_233025_4e9c1c` | `COMPLETED_WITH_ARTIFACTS` | 3 | 32601 ms | $0.277247 | $0.018118 | 37457 | 1965 | 31744 |
| 2 | workArea to 3D contract | `code_contract_audit` | `t_20260630_233103_8e4760` | `COMPLETED_WITH_ARTIFACTS` | 11 | 79835 ms | $0.679781 | $0.032165 | 59642 | 5337 | 435072 |
| 3 | README onboarding review | `docs_review` | `t_20260630_233223_a8b76d` | `COMPLETED_WITH_ARTIFACTS` | 7 | 41071 ms | $0.341575 | $0.020669 | 41728 | 2445 | 107520 |
| 4 | Next low-risk task candidate | `next_task_planning` | `t_20260630_233307_df8471` | `COMPLETED_WITH_ARTIFACTS` | 5 | 58777 ms | $0.386763 | $0.021073 | 39815 | 3831 | 116096 |

## Control Evidence

- `quick_triage`, `code_contract_audit`, and `next_task_planning` prompts included seeded evidence.
- All four prompts included the no-subagent / no-Agent contract.
- No task hit `error_max_turns` or `max_turns_no_diff`.
- The `travel_with_me` repository remained clean after the run.
- `changed_files=[]` for all four read-only samples.

## Task-Level Findings

### Project config health

The worker completed in 3 turns and confirmed the project command contract is internally consistent:

- `npm test` maps to Vitest.
- `npm run check` exists and is documented.
- The World stack declaration matches the project dependencies and architecture.

Minor finding: README describes `npm run check` too narrowly as Prettier + ESLint, while the actual command also runs architecture, provenance, landmark, and ledger checks.

### workArea to 3D contract

The previously fragile `code_contract_audit` shape completed successfully. It still used 11 turns, so the seed evidence helped completion but did not make this profile as cheap as `quick_triage`.

The outcome is still useful: this is the profile most likely to need further hard controls if future samples regress.

### README onboarding review

The docs review completed without seeded evidence and without max-turn failure. This suggests the required output contract and no-Agent instruction alone are sufficient for simple docs tasks.

### Next task planning

The worker returned one concrete candidate instead of over-searching:

- Add unit tests for pure functions in `js/route-planner.js`.
- Target: `js/__tests__/route-planner.test.js`.
- Suggested checks: targeted Vitest command and `npm run check`.

This confirms the "one candidate is enough" strategy is working for this profile.

## Assessment

This small sample passes the immediate post-fix check:

- 4/4 completed.
- 0 max-turn failures.
- 0 changed files.
- Business repository remained clean.
- Estimated Codex orchestration tokens stayed low relative to worker tokens.

The main remaining concern is sample size. The result is strong enough to justify one larger 8-sample or 10-sample run, but not enough to claim production-level reliability.

## Recommended Next Step

Run an 8-sample confirmation set:

- 2 `quick_triage`
- 2 `code_contract_audit`
- 2 `docs_review`
- 2 `next_task_planning`

Acceptance target:

- at least 7/8 completed,
- 0 `max_turns_no_diff`,
- no business-repo writes,
- average backend calculated worker cost below $0.035 per task.
