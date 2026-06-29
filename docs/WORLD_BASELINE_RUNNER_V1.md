# World Baseline Runner v1

World Baseline Runner v1 records same-task no-World Codex baselines so World
can compare its own Codex planning/review usage against a Codex-only control.

## Command

Create a replay estimate from stored artifacts:

```text
uv run ai-dispatcher record-task-baseline --task-id <task_id>
```

Record actual Codex-only usage from a manual control run:

```text
uv run ai-dispatcher record-task-baseline \
  --task-id <task_id> \
  --input-tokens <n> \
  --output-tokens <n> \
  --actual
```

## Data

Baselines are stored in SQLite table `task_baselines` and in each task run dir:

```text
baselines/task_baselines.jsonl
```

The task `token_ledger.json` is refreshed after every baseline record.

## Modes

`replay_estimate`

- Uses task artifacts such as `task.json`, `route.json`, `result.json`,
  `verify/verify.json`, `review/review.json`, and `final.md`.
- Estimates tokens with the existing UTF-8 bytes / 4 estimator.
- Sets `actual_codex_used=false`.
- Ledger status: `counterfactual.status = estimated`.

`manual actual`

- Uses explicit token counts from a same-task Codex-only control run.
- Sets `actual_codex_used=true`.
- Ledger status: `counterfactual.status = measured`.

## Guardrail

Replay estimates must not be presented as measured Codex quota savings. They
are a planning and trend signal only.

Measured savings require a real Codex-only control with the same task goal,
similar acceptance criteria, and comparable review outcome.
