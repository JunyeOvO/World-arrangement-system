# World MVP Quality Matrix and Real-Use Evaluation

Date: 2026-06-29

## Scope

This evaluation implemented the MVP quality feedback loop and tested it against the registered `travel_with_me` project with small, production-like read-only tasks. The task scope was intentionally narrow: identify the project stack, choose minimal quality gates, and avoid broad repository scans or business-repo writes.

## Implemented Quality Loop

- Added durable `task_outcomes` records for terminal and actionable task states.
- Added outcome derivation for `success`, `failed`, `approval`, `cancelled`, and degraded/mock cases.
- Added quality fields: `quality_state`, `user_acceptance`, `tests_passed`, `build_passed`, `review_approved`, `changed_files_count`, `codex_rework_required`.
- Added Console API: `GET /api/metrics/quality`.
- Added Console Metrics `Quality Matrix` view with success, acceptance, review, and rework rates.
- Added historical outcome backfill from existing task artifacts.

## Real Evaluation Runs

| Task | Status | Route | Cost | Input | Output | Cache read | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `t_20260629_110439_d1b995` | `CANCELLED` | Claudecode / Deepseek-V4-pro, then Opencode / GLM-5.2 fallback | $1.0943 | 69,775 | 13,476 | 916,040 | Exposed read-only no-diff fallback waste. |
| `t_20260629_111233_8226db` | `FAILED_FINAL` | Claudecode / Deepseek-V4-flash | $0.2284 | 33,731 | 1,338 | 27,648 | Worker produced useful answer, but verify wrongly ran `npm test`. |
| `t_20260629_111614_868955` | `FAILED_FINAL` | Claudecode / Deepseek-V4-flash | $0.2436 | 33,779 | 1,934 | 27,648 | Same class of failure; `vitest.config.js` / `playwright.config.js` names triggered test intent. |
| `t_20260629_111747_b45f41` | `COMPLETED_WITH_ARTIFACTS` | Claudecode / Deepseek-V4-flash | $0.2742 | 33,959 | 2,446 | 62,208 | Fixed path: no tests run, no files changed, quality outcome verified and accepted. |

Measured cost for the evaluation loop was $1.8406. Most of that was caused by defects discovered during the test, not by the fixed happy path.

## High-Priority Issues Fixed

### 1. Read-Only No-Diff Fallback Waste

For read-only work, a worker can produce a valid textual result without a patch. The previous scheduler treated `max_turns_no_diff` as a worker failure and escalated to fallback routes, which caused unnecessary model calls.

Fix:
- Salvage valid read-only worker output when failure reason is `max_turns_no_diff` or `worker_no_diff`.
- Continue to verification/review without fallback if there are no changed files and the extracted worker text is usable.

### 2. Read-Only Tasks Were Over-Verified

Tasks that asked for recommended test commands were interpreted as asking World to run those commands. File names such as `vitest.config.js` and `playwright.config.js` also triggered test execution.

Fix:
- Verification intent now requires explicit execution language such as `run npm test`, `run vitest`, `运行测试`, or `执行测试`.
- Command references like "输出最小测试命令" no longer force project verification.
- Read-only no-change results complete as `COMPLETED_WITH_ARTIFACTS` with an internal skipped-read-only review.

## Does It Save Codex Work?

Current answer: yes for narrow read-only project triage after the fixes, but not yet proven for broad coding tasks.

Evidence:
- The fixed task completed without Codex review and without business repository writes.
- The system produced a structured project assessment, minimal test-gate recommendation, risks, route metrics, token usage, cost, and quality outcome.
- Console can now separate useful accepted results from failures and approval/degraded states.

Quota implication:
- To extend a Codex weekly quota from roughly 2 days to 7 days, Codex usage must fall to about 28.6% of the previous direct-Codex workload.
- World can contribute to that target only if Codex remains a lightweight dispatcher/reviewer and cheap workers handle most read-only analysis, narrow audits, and routine low-risk tasks.
- The current MVP still needs more successful coding-task samples before claiming that target for implementation work.

## Next Optimization Targets

1. Add an explicit `read_only` or `expected_diff=false` task field instead of deriving it only from text.
2. Add a preflight dependency health check for registered projects, especially missing `node_modules`, before any verify command runs.
3. Record `task_outcomes` for stale/retry states once they become terminal or user-actionable.
4. Add user acceptance controls in Console so accepted/rejected is not only inferred from review state.
5. Use low-cost routes by default for read-only triage, then escalate only when the result is missing or degraded.
6. Run a 10-task post-fix sample across read-only, test-only, and one-file bugfix tasks before expanding to higher-risk work.

## Acceptance State

MVP quality matrix is usable for current evaluation:
- Real token and cost metrics are recorded.
- Accepted vs rejected outcomes are visible.
- High-priority routing/verification defects found by real use were fixed.
- The fixed read-only task path demonstrates measurable Codex review avoidance.
