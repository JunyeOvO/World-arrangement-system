# World GRASP/GoF Refactor Roadmap

Date: 2026-06-30

Goal: refactor World toward clearer GRASP responsibility assignment and GoF-style extensibility without changing external behavior.

## Current Architecture Pressure

`orchestrator/scheduler.py` has historically acted as a god module:

- task lifecycle orchestration;
- approval/risk/route coordination;
- worker invocation;
- read-only prompt construction;
- profile-specific prompt strategies;
- seed evidence selection and redaction;
- result salvage and failure handling;
- artifact and outcome recording.

This violates low coupling and high cohesion. It also makes post-fix behavior harder to test without running the whole scheduler.

## Refactor Principles

GRASP:

- **Information Expert**: move logic to the module that owns the information needed to decide.
- **Controller**: keep `OrchestratorService` as workflow coordinator, not business-rule owner.
- **Low Coupling / High Cohesion**: isolate prompt construction, routing, verification, and failure classification.
- **Protected Variations**: hide profile-specific prompt/seed rules behind a stable prompt builder API.

GoF:

- **Strategy**: named read-budget profiles select prompt and seed strategies.
- **Builder**: worker prompt construction becomes a composable builder-style module.
- **Facade**: scheduler calls one stable `build_worker_prompt(...)` entrypoint.
- **Template Method**: read-only output contract provides a fixed result skeleton with profile-specific sections.

## Slice 1 Implemented: Worker Prompt Boundary

Moved worker prompt construction out of `orchestrator/scheduler.py` into `orchestrator/worker_prompt.py`.

New ownership:

- `scheduler.py`: lifecycle orchestration and worker dispatch.
- `worker_prompt.py`: prompt templates, read-only output contracts, profile strategies, seed evidence selection, seed excerpt redaction.

Pattern mapping:

- `build_worker_prompt(...)`: Facade + Builder entrypoint.
- `_worker_profile_strategy(...)`: Strategy selector for read-budget profiles.
- `_read_only_required_output_contract(...)`: Template Method-style output skeleton.
- `_read_only_seed_context(...)`: Information Expert for seed evidence.

The scheduler keeps `_worker_prompt(...)` only as a compatibility wrapper:

```python
return build_worker_prompt(task, route, task_requires_diff=_task_requires_diff)
```

## Verification

Targeted tests:

```text
uv run pytest tests/test_scheduler.py tests/test_mimo_vision_adapter.py tests/test_workers.py tests/test_failure_classifier.py
66 passed
```

## Next Refactor Slices

1. **Worker attempt strategy**
   - Extract retry-chain execution and worker-result normalization from `scheduler.py`.
   - Candidate module: `orchestrator/worker_attempts.py`.
   - Patterns: Strategy for retry attempts, Adapter for worker result normalization.

2. **Read-only completion policy**
   - Move `_read_only_failure_summary`, partial salvage, and read-only completion decisions into a policy module.
   - Candidate module: `orchestrator/read_only_completion.py`.
   - Patterns: Chain of Responsibility for salvage sources.

3. **Task lifecycle state controller**
   - Isolate status transitions and event payload construction from direct scheduler calls.
   - Candidate module: `orchestrator/task_lifecycle.py`.
   - Patterns: State + Facade.

4. **Baseline/outcome recording service**
   - Move token ledger, baseline replay, and outcome write sequencing behind a recording service.
   - Candidate module: `orchestrator/task_recording.py`.
   - Patterns: Facade.

5. **Console query view models**
   - Keep DB queries, dashboard status derivation, and display serialization separated.
   - Candidate modules already partly exist under `orchestrator/console/`; continue splitting behavior from presentation.

## Completion Criteria For Full Goal

The GRASP/GoF refactor should be considered complete only when:

- `scheduler.py` is primarily orchestration glue, not prompt/failure/recording business logic.
- Profile behavior is testable without instantiating `OrchestratorService`.
- Worker retry and read-only salvage policies are independently unit-tested.
- Existing CLI, Console, and worker tests pass.
- Real read-only sample behavior remains at or above the last verified 8/8 small-sample success.
