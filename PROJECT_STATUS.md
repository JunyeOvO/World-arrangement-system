# World Project Status

Date: 2026-07-01

This file summarizes the current repository state after the recent World
self-adjustment, Codex debugging, documentation cleanup, file organization, and
quality-gate reset.

## Repository State

- Branch: `main`
- Remote: `origin/main`
- Current source of truth for roadmap and gates:
  `docs/WORLD_CURRENT_UPGRADE_PLAN_AND_QUALITY_GATE_2026-07-01.md`
- Current task execution protocol:
  `docs/WORLD_EXECUTION_PROTOCOL.md`
- Historical plans and sample reports:
  `docs/archive/obsolete-2026-07-01/`

Recently organized work:

- Root `PLAN.md` was archived to
  `docs/archive/obsolete-2026-07-01/PLAN.md`.
- `docs/README.md` is the documentation index.
- Historical plans, samples, scans, and old gate reports are kept under
  `docs/archive/obsolete-2026-07-01/` as evidence only.
- Console Metrics usage aggregation was split from
  `orchestrator/console/queries.py` into
  `orchestrator/console/metrics_usage.py`, with focused coverage in
  `tests/test_console_metrics_usage.py`.

Current docs should link to current sources of truth, not to archived sample
reports or superseded plans.

## Current Capability

World is usable as a local execution backend for Codex-assisted work:

- bounded read-only project triage;
- code contract audits;
- docs review;
- next-task planning;
- small low-risk fixes with explicit tests and Codex review;
- token/cost and quality outcome tracking.

World is not yet approved for unsupervised production code changes, automatic
merge, or broad autonomous feature delivery.

## Current Quality Baseline

Latest known full-suite baseline:

```powershell
uv run pytest
```

Expected result at the time of this status file:

- 552 tests passing.

Security hygiene:

- Real secrets must not be committed.
- Keep only `.env.example` and `profiles/*.env.example` in git.
- Runtime output, caches, `worker/`, `.venv/`, and local settings remain ignored.

## Immediate Next Work

1. Implement the Phase B quality warning layer:
   - `turns_over_profile_budget`;
   - `worker_declared_partial`;
   - terminal token-ledger status refresh;
   - Console visibility for quality warnings.
2. Run the 6-task read-only confirmation sample described in the current gate
   plan.
3. Start Project Memory V2 only after the quality warning layer is stable.

## Commit Discipline

Before any commit:

```powershell
git status --short --branch
uv run pytest
rg -n "sk-[A-Za-z0-9_-]{16,}|API_KEY|SECRET|TOKEN|PASSWORD" -g "!*.example" -g "!uv.lock" .
```

Stage only files that belong to the current task. Do not stage unrelated local
WIP.
