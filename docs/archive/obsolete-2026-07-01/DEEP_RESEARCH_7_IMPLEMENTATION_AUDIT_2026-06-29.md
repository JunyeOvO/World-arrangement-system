# Deep Research 7 Implementation Audit - 2026-06-29

This audit tracks the implementation state of the priority items from
`deep-research-report (7).md` against the current World system codebase.

## Scope

The research report's near-term priorities were:

1. Project Memory MVP
2. Router v2 cost/success-aware routing
3. Static worker permission templates
4. Unified Codex + worker token/cost ledger
5. Three-layer status model + reaper
6. Console cost/approval/explanation MVP
7. 20-sample calibration and same-task baseline workflow

## Implementation Status

| Area | Status | Current evidence | Remaining limit |
|---|---|---|---|
| Project Memory MVP | MVP implemented | `orchestrator/project_memory.py`, memory injection tests, redaction tests | No semantic/vector index yet; memory quality depends on profile freshness |
| Router cost/success awareness | MVP implemented | `orchestrator/routing/scorer.py`, `orchestrator/router_v3.py`, `tests/test_router_v3.py`, commit `c7c55d8` | Uses bounded heuristic scoring, not learned optimization |
| Static worker permissions | MVP implemented | `orchestrator/worker_permissions.py`, verifier command guard tests, commit `ab36d66` | Permission templates still need more real-project policy tuning |
| Unified token/cost ledger | MVP implemented | `orchestrator/token_ledger.py`, Codex usage events, Console efficiency metrics, commit `eed4d27` | Codex planning tokens are estimated unless manually recorded as actual |
| Same-task baseline workflow | MVP implemented | `orchestrator/baselines.py`, CLI `record-task-baseline`, Console baseline comparison, commits `3396e11`, `fded9f1` | Strongest claims require real Codex-only measured samples |
| Status model + reaper | MVP implemented | `orchestrator/dashboard_status.py`, scheduler stale reaper, Console status tests | Retry resume remains intentionally unsupported; new task submission is still the safe path |
| Console explanation surface | MVP implemented | Metrics quality/efficiency/baseline panels and structured route detail card, commit `e19b920` | Browser-side route explanation is still read-only; no route what-if simulator |

## Current Verification

- `uv run pytest`: 365 passed.
- `npm.cmd run build` in `console-web`: passed.
- Console local HTTP check: `http://127.0.0.1:8765/` returned 200.
- Secret scan only matched test fixtures used for redaction coverage.

## Objective Assessment

World has reached a usable local MVP for "Codex-assisted execution backend":

- It can reduce repeated Codex context loading when Project Memory is current.
- It can route low-risk or single-file tasks away from expensive backends when historical success supports that choice.
- It can show whether savings claims are measured or estimated instead of presenting worker-token savings as Codex quota savings.
- It keeps high-risk operations behind approval and verification boundaries.

It is not yet a self-optimizing autonomous development platform:

- Historical routing is heuristic and should remain conservative until there are enough measured task outcomes.
- Codex quota savings are not proven globally without a larger measured sample.
- Worker context quality still depends on generated project memory and task scope quality.
- Retry repair is limited; failed or stale tasks should usually be resubmitted with a clearer goal.

## Next Validation Gate

Before claiming "two days of Codex quota becomes one week" as measured:

1. Run at least 20 same-task samples across docs, read-only analysis, targeted patch, tests, config repair, and hard bugfix.
2. Record one baseline for each task:
   - actual Codex-only tokens when affordable, or
   - replay baseline when actual measurement is not available.
3. Record task outcomes:
   - success or failure
   - changed files
   - tests/build result
   - review result
   - user acceptance
   - whether Codex rework was needed
4. Compare:
   - Codex tokens saved
   - worker cost added
   - success rate
   - retry rate
   - stale/reaper rate
   - misroute/misblock rate

The system should only claim quota extension when Codex token reduction is
measured or clearly labeled as replay-estimated, and quality is not worse than
the no-World baseline.
