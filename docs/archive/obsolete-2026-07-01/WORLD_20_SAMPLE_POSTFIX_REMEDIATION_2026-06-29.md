# World 20-Sample Post-Fix Remediation

Date: 2026-06-29

This note records the immediate fixes made after the 20-sample real validation pass.

## Problems Addressed

The validation showed three high-impact defects:

1. Read-only tasks could be routed as patch tasks when the goal contained words like fix, config, README, or documentation.
2. Read-only workers that hit the turn budget could fail even when the stream already contained useful observations.
3. Replay baseline metadata listed runtime artifacts such as worktrees, worker streams, and control files, making baseline review noisy.

## Implemented Fixes

### Read-Only Routing Override

`task_mode=read_only` and `expected_diff=false` now take precedence over keyword-based task shape inference.

Result:

- Read-only project analysis routes to `review_only`.
- Patch-oriented retry chains are removed for read-only tasks.
- Explicit implementation task shapes are downgraded to `review_only` unless they are safe read-only shapes.

### Partial Read-Only Result Salvage

Worker streams are now scanned for meaningful partial observations when a read-only task fails with `max_turns_no_diff` or `worker_no_diff`.

Supported stream shapes include:

- `result` text
- assistant message content
- `text` / `part.text`
- `content_block_delta` chunks

When a meaningful partial result is found, the task is marked with:

- `partial_result=true`
- terminal status `COMPLETED_WITH_PARTIAL_ARTIFACTS`
- review reason `read_only_partial_salvage`

This status is counted as Done, not Failed, Running, Queued, Approval, or Alert.

### Replay Baseline Runtime Filtering

Replay baseline metadata now keeps only stable review artifacts, such as:

- `task.json`
- `route.json`
- `result.json`
- `verify/verify.json`
- `review/review.json`
- `final.md`
- `metrics.json`
- `token_ledger.json`
- `outcome.json`

Runtime paths under `worktrees/`, `worker/`, `control/`, and `attempts/` are excluded from the metadata artifact path list.

## Verification

Targeted tests passed:

```text
uv run pytest tests/test_router_v3.py tests/test_scheduler.py tests/test_baselines.py tests/test_dashboard_status.py tests/test_state_machine.py tests/test_outcomes.py
76 passed
```

## Next Validation

Run a small post-fix sample focused on the previous failure modes:

1. Five read-only project analysis tasks with fix/config/doc keywords.
2. Three next-task planning tasks with tight budgets.
3. Two replay-baseline recording checks on completed runs.

Expected improvement:

- Read-only tasks should no longer trigger Opencode fallback chains.
- Budget-limited read-only tasks should become partial artifacts when useful observations exist.
- Baseline records should stay compact and free of runtime path noise.
