# World Current Upgrade Plan and Quality Gate

Date: 2026-07-01

This is the current source of truth for World system upgrades, quality gates,
and production-readiness boundaries. Older sample reports, broad upgrade plans,
and scan notes have been moved to `docs/archive/obsolete-2026-07-01/`.

## 1. Current Position

World is usable today as a local execution backend that helps Codex with
bounded reading, triage, audit, verification, and small scoped fixes. It is not
yet a fully autonomous production coding agent.

The practical target remains:

- Codex handles intent, dispatch, final judgment, and high-risk review.
- World workers handle bounded evidence gathering, low-risk implementation,
  repetitive checks, and structured artifacts.
- The system extends Codex quota by reducing repeated Codex repository reads,
  not by multiplying unbounded worker exploration.

Current status:

| Area | Status | Production meaning |
| --- | --- | --- |
| Explicit task protocol | Usable | `task_mode`, `expected_diff`, `verification_policy`, and read budgets are first-class fields. |
| Read-only worker assistance | MVP usable | Small samples reached usable completion, but broad audits still need strict budgets. |
| Patch execution | Limited beta | Safe for small scoped fixes with tests and Codex review. |
| Token/cost ledger | Usable with caveats | Worker token/cost is tracked; Codex planning/review is partly estimated unless measured. |
| Console status model | Improved | Running/Queued/Failed/Approval/Alerts are derived from runtime liveness, not raw status alone. |
| Quality outcome recording | MVP usable | Outcomes exist, but acceptance and rework labels need more same-task samples. |
| Project memory | MVP usable | Reduces repeated reads, but not yet a durable semantic codebase memory. |
| Autonomy | Restricted | No auto-merge, no unsupervised high-risk changes, no production deployment without user approval. |

## 2. Main Defects To Fix Next

These are based on recent Codex debugging and World self-adjustment results.

### 2.1 Context Reuse Is Still Weak

Workers still spend too much effort rediscovering the repository. Project
memory and seed evidence help, but they are not yet enough for large or
ambiguous tasks.

Required upgrade:

- Build project memory v2 with stable module summaries, ownership boundaries,
  verified commands, known hazards, and recently fixed defects.
- Refresh memory from the active worktree before worker execution.
- Store per-task lessons only when a result is verified or explicitly accepted.

### 2.2 Executor Control Must Be Harder Than Prompt Text

Prompt guidance alone is not sufficient. The executor must enforce limits and
warnings.

Required upgrade:

- Enforce `max_files`, `max_searches`, `max_worker_turns`, and
  `max_duration_sec` at the worker adapter layer where possible.
- Record `turns_over_profile_budget`.
- Record `worker_declared_partial`.
- Track `silent_max_turns_no_output`.
- Force read-only workers to emit a partial structured result before the last
  allowed turn.

### 2.3 Quality Signals Need To Be More Honest

The system must not treat partial or unverified results as fully successful.

Required upgrade:

- Separate `completed`, `partial_completed`, `verified`, `accepted`,
  `needs_codex_rework`, and `unsafe_to_apply`.
- Never infer `tests_passed` from build success or missing data.
- Mark unknown model pricing as unpriced instead of silently `$0`.
- Surface quality warnings in Console even when task status is terminal.

### 2.4 Patch Tasks Need A Narrower Adoption Path

Read-only assistance is more mature than patch execution. Patch execution must
expand only through measured low-risk slices.

Required upgrade:

- Start with one-file or two-file low-risk fixes.
- Require changed-file allowlist and forbidden-path scan.
- Require verification matching `verification_policy`.
- Require Codex review before commit or push.

## 3. Upgrade Roadmap

### Phase A: Documentation and Gate Reset

Status: in progress.

Deliverables:

- Archive historical upgrade plans and sample reports.
- Establish this document as the current source of truth.
- Update README to point to current docs only.
- Keep historical evidence in archive, not in the main docs list.

Exit gate:

- README "Useful Docs" no longer points to obsolete plans.
- Historical sample reports are under `docs/archive/obsolete-2026-07-01/`.
- `uv run pytest` passes.

### Phase B: Quality Warning Layer

Goal: make hidden partial/over-budget results visible.

Deliverables:

- `turns_over_profile_budget` quality warning.
- `worker_declared_partial` parser for read-only final text.
- Terminal token ledger refresh so `token_ledger.task_status` matches final DB
  status.
- Console quality warnings panel or field in task detail.

Exit gate:

- 6-task read-only confirmation sample:
  - 6/6 usable completions.
  - 0 `silent_max_turns_no_output`.
  - 0 business repo writes.
  - 0 hidden over-budget success without a warning.
  - terminal token ledger status matches final DB status.

### Phase C: Project Memory V2

Goal: reduce repeated worker scans.

Deliverables:

- Stable repo map with module ownership and entrypoints.
- File summary cache keyed by content hash.
- Known hazards list: forbidden paths, fragile contracts, platform-specific
  commands, test caveats.
- Verified command registry per project.
- Memory source metadata: repo path, worktree path, commit/ref, refresh time.

Exit gate:

- Two repeated read-only tasks on the same project show lower file reads or
  lower worker turns on the second run without lower result quality.
- Memory is redacted and never includes secrets.

### Phase D: Executor-Enforced Read Budgets

Goal: move from prompt-only guidance to runtime-enforced controls.

Deliverables:

- Adapter-level counters for file reads/searches where tools expose them.
- Hard timeout and salvage path for read-only tasks.
- Profile-specific last-turn warning.
- Mandatory partial result artifact when a read-only worker times out after
  producing useful evidence.

Exit gate:

- `quick_triage`, `docs_review`, `code_contract_audit`, and
  `next_task_planning` each have tests for budget warnings and salvage.

### Phase E: Measured Codex Savings

Goal: prove whether World helps Codex quota in real use.

Deliverables:

- Same-task Codex-only baseline recording flow.
- Explicit `actual_codex_used` flag for planning and review.
- Console efficiency view separating measured, estimated, and unknown savings.
- Minimum sample set across docs, read-only audit, small patch, and test-only
  tasks.

Exit gate:

- At least 20 same-task samples.
- At least 10 measured Codex-only baselines.
- Reported savings clearly labeled as measured, estimated, or unavailable.
- Codex token share target: under 28.6% of Codex-only usage for the same task
  class before claiming the "2 days to 7 days" quota goal.

### Phase F: Patch Beta

Goal: safely expand from read-only help into real small fixes.

Deliverables:

- Low-risk patch profile.
- Changed-file allowlist.
- Forbidden-path and secret scans.
- Required verification command based on project registration.
- Codex review before commit/push.

Exit gate:

- 10 low-risk patch tasks:
  - at least 8 accepted without manual rewrite;
  - 0 forbidden path writes;
  - 0 secret exposure;
  - 0 unverified success labels;
  - all failures return actionable root cause and next step.

## 4. Quality Gates

### 4.1 Repository Gate

Required before any commit:

```powershell
uv run pytest
rg -n "sk-[A-Za-z0-9_-]{16,}|API_KEY|SECRET|TOKEN|PASSWORD" -g "!*.example" -g "!uv.lock" .
git status --short --branch
```

Pass criteria:

- Tests pass.
- No real secrets are reported.
- Only intentional files are staged.
- Existing unrelated WIP remains unstaged.

### 4.2 Task Gate

| Task mode | Required gate |
| --- | --- |
| `read_only` | `changed_files=[]`; structured final or partial artifact; no business repo writes. |
| `docs` | docs diff only; no code/config/runtime changes unless explicitly requested. |
| `test` | test files or test config only; failing tests must include root cause. |
| `patch` | changed-file review, forbidden-path scan, verification command, Codex review. |
| `audit` | evidence paths, severity, reproducible risk, and no file writes. |

### 4.3 Release Gate

World is not "production-ready" unless all are true:

- No open known P0.
- No unmitigated P1 in execution, secrets, DB consistency, or approval flow.
- `uv run pytest` passes on the current tree.
- Console status and token/cost views do not mislabel unknown data as success.
- Read-only confirmation sample passes.
- Patch beta sample passes before expanding automatic patch scope.

### 4.4 Console Gate

Console APIs must obey:

- `GET /api/console/snapshot` is read-only.
- Mutating actions require explicit POST endpoints.
- Task status is derived through the dashboard status model, not raw DB status
  alone.
- Stale executing tasks must not count as Running without fresh heartbeat or
  valid control liveness.
- Alerts must be explainable and dismissible/resolvable through explicit
  actions.

### 4.5 Worker Output Gate

Every worker result must include:

- concise conclusion;
- evidence files or artifacts;
- changed files;
- tests/verification performed;
- risks and next step;
- explicit partial/degraded marker when applicable.

Unacceptable outputs:

- "approved" when worker used a mock/degraded path without clear marking;
- "tests passed" when no test ran;
- cost `$0` for an unpriced model;
- hidden over-budget success without a warning.

## 5. Production Use Policy

Use World now for:

- read-only project assessment;
- root-cause narrowing;
- contract audits;
- docs review;
- small local fixes with tests;
- repeated validation samples.

Do not use World autonomously for:

- auth, payment, production database, or secret-handling code;
- large feature delivery;
- multi-repo changes;
- deploy or merge automation;
- tasks without verifiable local evidence.

## 6. Immediate Next Tasks

1. Implement Phase B quality warning layer.
2. Run the 6-task read-only confirmation sample.
3. Implement Project Memory V2 source metadata and hazard summaries.
4. Add measured Codex-only baselines for selected repeated task classes.
5. Begin patch beta only after Phase B exits cleanly.

