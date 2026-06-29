# World Token Ledger v1

World Token Ledger v1 gives every task a single accounting artifact for Codex
planning/review usage, worker model usage, memory/cache evidence, and known USD
cost.

## Goal

The ledger exists to answer one operational question:

> Did World reduce the amount of Codex work required for this task?

v1 does not claim that answer directly. It records the evidence needed to make
the claim later with a same-task no-World baseline.

## Artifact

Each task run writes:

```text
token_ledger.json
```

The artifact is refreshed after:

- Codex dispatch usage is recorded.
- Codex review usage is recorded.
- Worker attempt metrics are written.

It is also exposed through the Console task artifact whitelist and task detail
payload.

## Sections

### `codex`

Records local estimates for Codex-side planning and review phases.

Current source:

- `planning_dispatch`
- `world_review`

Token counts are estimated from UTF-8 payload bytes because local Codex quota
telemetry is not exposed.

### `worker`

Records adapter-reported worker usage from task metrics:

- input tokens
- output tokens
- cache-read input tokens
- model/agent attempts
- calculated USD cost using backend model pricing
- adapter-reported cost, when an adapter provides it
- project memory hit/miss counts

Worker cost is the trusted USD cost source in v1 when the model is in the
pricing table.

### `combined`

Combines Codex estimated tokens with worker reported tokens so the task has one
total token view.

Known USD cost currently means worker model cost only. Codex cost is not
included because the local system does not receive Codex billing or quota
telemetry.

### `quota_evidence`

Summarizes the values needed for quota-saving analysis:

- Codex token share
- worker token share
- actual Codex event count
- memory hit/miss count
- cache-read input tokens

### `counterfactual`

v1 explicitly marks the no-World baseline as `not_measured`.

Before claiming measured Codex savings, run a same-task control where Codex
performs planning, implementation, and review without World delegation, then
compare the same task category and acceptance result.

## Trust Boundary

Trusted:

- worker input/output/cache tokens when the adapter stream reports them
- backend-calculated worker model cost
- memory hit/miss counts from Project Memory
- Codex phase payload estimates as rough local accounting

Not trusted as final proof:

- Codex planning/review token estimates as exact quota usage
- savings percentage without a same-task no-World control
- adapter-reported USD cost when backend pricing is available

## Next Step

The next P0 improvement is a baseline runner that stores matched no-World
Codex control samples in the same ledger format. That will let Console show
measured Codex reduction instead of the current evidence-only view.
