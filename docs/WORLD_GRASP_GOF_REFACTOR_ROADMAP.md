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

## Slice 2 Started: Worker Attempt Strategy

Moved retry-chain planning out of `orchestrator/scheduler.py` into
`orchestrator/worker_attempts.py`.

New ownership:

- `scheduler.py`: consumes the planned attempt chain during task execution.
- `worker_attempts.py`: retry-chain construction, retryable-failure predicates, failed-diff recovery predicate.

Pattern mapping:

- `build_retry_chain(...)`: Strategy entrypoint for route-specific escalation plans.
- route-provided `retry_chain`: Strategy object supplied by the router.
- string/dict fallback model handling: Adapter-style normalization into one attempt shape.

The scheduler imports compatibility aliases so existing tests and call sites continue to work:

```python
from .worker_attempts import build_retry_chain as _build_retry_chain
```

Remaining work in this slice: move worker-result normalization and attempt lifecycle hooks out of
`_execute` after this smaller boundary is stable.

## Slice 3 Implemented: Read-Only Completion Policy

Moved read-only completion rules out of `orchestrator/scheduler.py` into
`orchestrator/read_only_completion.py`.

New ownership:

- `scheduler.py`: asks whether a read-only task can finish, whether verification can be skipped, and which review payload to write.
- `read_only_completion.py`: diff requirement detection, project-verification intent detection, partial-result salvage, worker stream text extraction, read-only review payload.

Pattern mapping:

- `task_requires_diff(...)`: Policy/Strategy boundary for execution mode.
- `read_only_failure_summary(...)`: Chain of Responsibility-style salvage from success text, stream deltas, then meaningful raw summary.
- `read_only_review(...)`: Factory-style construction of the terminal review payload.

This isolates the logic that determines when a read-only worker result is a valid artifact instead of a failed patch attempt.

## Slice 4 Implemented: Attempt Metrics Recording

Moved regular attempt metrics and token-ledger refresh out of `orchestrator/scheduler.py` into
`orchestrator/attempt_recording.py`.

New ownership:

- `scheduler.py`: signals that an attempt result should be recorded.
- `attempt_recording.py`: collects worker stream metrics, reads memory stats from `task.json`, writes attempt/root metrics artifacts, updates DB metrics, refreshes `token_ledger.json`.

Pattern mapping:

- `AttemptMetricsRecorder`: Facade over metrics collection, DB upsert, and token ledger refresh.
- `memory_metric_kwargs(...)`: Information Expert for extracting memory hit/miss counts from task artifacts.

This removes another persistence concern from the scheduler and gives metrics recording a direct unit-test boundary.

## Slice 5 Implemented: Worker Permission Audit

Moved worker permission preflight and changed-file permission audit into
`orchestrator/worker_permission_audit.py`.

New ownership:

- `scheduler.py`: asks whether a worker may proceed.
- `worker_permission_audit.py`: derives declared write paths, checks worker write policy, records permission audit events.

Pattern mapping:

- `WorkerPermissionAuditor`: Facade over permission policy and audit event persistence.
- `declared_write_paths(...)`: Information Expert for consolidating owned, target, and planned write paths.

This keeps permission event payload construction out of scheduler and gives worker permission auditing a direct test boundary.

## Slice 6 Implemented: Task Lifecycle Controller

Moved the status-transition write flow into `orchestrator/task_lifecycle.py`.

New ownership:

- `scheduler.py`: requests a status transition.
- `task_lifecycle.py`: updates task status, syncs task artifacts, appends lifecycle events, triggers terminal outcome hooks.

Pattern mapping:

- `TaskLifecycleController`: Facade around DB status updates, event persistence, artifact sync, and outcome hooks.
- terminal outcome hook: Template Method-style extension point supplied by the scheduler.

This centralizes state-transition side effects while leaving existing outcome derivation untouched.

## Slice 7 Implemented: Task Routing Policy

Moved route override and World-enabled project policy helpers into `orchestrator/task_routing.py`.

New ownership:

- `scheduler.py`: asks for a route and applies the returned policy.
- `task_routing.py`: determines World-enabled project flags, write policy, and forced route override normalization.

Pattern mapping:

- `apply_route_override(...)`: Strategy normalization for forced worker/model/variant execution.
- `world_enabled(...)` and `world_write_policy(...)`: Information Expert for project routing metadata.

This removes capability-profile construction and agent display-name derivation from scheduler.

## Slice 8 Implemented: Worker Attempt Executor

Moved the mechanical "run one worker attempt" flow into `orchestrator/worker_attempt_executor.py`.

New ownership:

- `scheduler.py`: iterates retry attempts and decides global task transitions such as retry, block, verify, review, publish.
- `worker_attempt_executor.py`: prepares attempt metadata, runs permission preflight, injects attempt-level AGENTS.md for OpenCode, emits worker-started events, invokes the worker adapter, classifies worker failure, salvages read-only partial results, writes attempt/root result artifacts, and records attempt metrics.

Pattern mapping:

- `WorkerAttemptExecutor`: Template Method for one attempt lifecycle.
- `WorkerAttemptOutcome`: explicit result object for scheduler decisions.
- injected `build_prompt`, `set_status`, `permission_auditor`, and `metrics_recorder`: Dependency Inversion and Low Coupling.

This is the main step toward making `scheduler.py` a workflow Controller instead of the owner of worker execution mechanics.

## Verification

Targeted tests:

```text
uv run pytest tests/test_scheduler.py tests/test_mimo_vision_adapter.py tests/test_workers.py tests/test_failure_classifier.py
66 passed
```

## Next Refactor Slices

1. **Worker attempt strategy**
   - Retry-chain planning extracted to `orchestrator/worker_attempts.py`.
   - Attempt execution mechanics extracted to `orchestrator/worker_attempt_executor.py`.
   - Next: split post-attempt decision policy for retry/block/recover/no-diff from the scheduler loop.
   - Patterns: Strategy for retry attempts, Adapter for worker result normalization.

1a. **Task routing policy**
   - Implemented in `orchestrator/task_routing.py`.
   - Next: split full route planning facade from `_route_for_task`.

2. **Read-only completion policy**
   - Implemented in `orchestrator/read_only_completion.py`.
   - Next: split policy tests into a dedicated test module when the scheduler compatibility layer is removed.
   - Patterns: Chain of Responsibility for salvage sources.

3. **Task lifecycle state controller**
   - Status transition side effects implemented in `orchestrator/task_lifecycle.py`.
   - Next: move richer event payload construction out of the long `_execute` flow.
   - Patterns: State + Facade.

3a. **Worker permission audit**
   - Implemented in `orchestrator/worker_permission_audit.py`.
   - Next: move non-permission status transition payloads into a lifecycle controller.

4. **Baseline/outcome recording service**
   - Attempt metrics and token-ledger refresh now live in `orchestrator/attempt_recording.py`.
   - Next: move baseline replay and outcome write sequencing behind recording services.
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
