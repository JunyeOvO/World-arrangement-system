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

## Slice 9 Implemented: Post-Attempt Decision Policy

Moved post-attempt decisions into `orchestrator/post_attempt_policy.py`.

New ownership:

- `scheduler.py`: applies the returned decision to task lifecycle and policy learning.
- `post_attempt_policy.py`: decides success, required-diff no-change failure, failed-worker-with-diff recovery, blocked/cancelled/non-retryable terminal handling, and retry payloads.

Pattern mapping:

- `decide_post_attempt(...)`: Strategy for interpreting an attempt result.
- `PostAttemptDecision`: explicit command object consumed by scheduler.

This separates "what the attempt result means" from "how the overall task workflow transitions".

## Slice 10 Implemented: Task Result Document Builder

Moved final Markdown rendering into `orchestrator/task_result_document.py`.

New ownership:

- `scheduler.py`: writes the generated `final.md` artifact.
- `task_result_document.py`: renders the task result document from task, route, worker, verify, and review payloads.

Pattern mapping:

- `build_final_markdown(...)`: Builder for final task documentation.

This removes presentation formatting from scheduler and gives the final result artifact a direct test boundary.

## Slice 11 Implemented: Task Verification Runner

Moved verification command selection, project verification execution, changed-file safety checks,
verify artifact writes, and verification failure classification into `orchestrator/task_verification.py`.

New ownership:

- `scheduler.py`: starts the VERIFYING phase and consumes a verification outcome.
- `task_verification.py`: applies `verification_policy`, skips project commands for eligible read-only tasks, runs verifier or dry verifier, writes verify artifacts, checks forbidden paths, and classifies verify failures.

Pattern mapping:

- `TaskVerificationRunner`: Facade over verifier, verification policy, safety checks, and artifact writes.
- `TaskVerificationOutcome`: explicit result object for scheduler decisions.

This removes another large tail section from `_execute` and puts the build/test gate behind a direct test boundary.

## Slice 12 Implemented: Task Review Runner

Moved Codex review input construction, review invocation, Codex usage recording, degraded-review blocking,
and review failure classification into `orchestrator/task_review.py`.

New ownership:

- `scheduler.py`: starts the CODEX_REVIEWING phase and applies the returned review outcome.
- `task_review.py`: builds review inputs, runs the review adapter, records Codex usage through an injected callback, and classifies review outcomes.

Pattern mapping:

- `TaskReviewRunner`: Facade over review gate execution and telemetry recording.
- `TaskReviewOutcome`: explicit result object for scheduler decisions.

This further separates review policy from workflow transition handling.

## Slice 13 Implemented: Task Publish Runner

Moved PR/patch publishing, `publish.json` writing, PR URL persistence, and publish-status mapping into
`orchestrator/task_publish.py`.

New ownership:

- `scheduler.py`: enters the publish phase and applies the returned publish outcome.
- `task_publish.py`: calls the publish adapter, writes publish artifacts, updates PR URL, and maps adapter statuses to task lifecycle status/events.

Pattern mapping:

- `TaskPublishRunner`: Facade over publish adapter, artifact write, and DB PR URL update.
- `TaskPublishOutcome`: explicit result object for lifecycle transition.

This leaves scheduler with less publish-specific branching and keeps publishing behavior independently testable.

## Slice 14 Implemented: Policy Learning Recorder

Moved task-completion policy learning recording into `orchestrator/policy_learning.py`.

New ownership:

- `scheduler.py`: signals policy learning with task/project context and outcome facts.
- `policy_learning.py`: adapts scheduler outcome facts into `PolicyUpdateEngine.on_task_complete(...)`.

Pattern mapping:

- `PolicyLearningRecorder`: Adapter/Facade over the policy update engine.

This keeps learned-policy persistence behind a direct test boundary while preserving scheduler compatibility wrappers.

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
   - Post-attempt decision policy extracted to `orchestrator/post_attempt_policy.py`.
   - Next: extract the full verify/review/publish tail from `_execute`.
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

4a. **Task result document**
   - Implemented in `orchestrator/task_result_document.py`.
   - Next: route all final artifact formatting through document builders instead of scheduler helpers.

4b. **Task verification runner**
   - Implemented in `orchestrator/task_verification.py`.
   - Next: extract publish tail into a separate service.

4c. **Task review runner**
   - Implemented in `orchestrator/task_review.py`.
   - Next: extract policy-learning recording.

4d. **Task publish runner**
   - Implemented in `orchestrator/task_publish.py`.
   - Next: extract remaining degraded/read-only terminal handlers.

4e. **Policy learning recorder**
   - Implemented in `orchestrator/policy_learning.py`.
   - Next: collapse remaining scheduler wrappers once call sites are simplified.

4f. **Terminal task handler**
   - Implemented in `orchestrator/terminal_handlers.py`.
   - Owns degraded mock completion and read-only completion artifact writes, Codex usage context, attempt metrics, and scheduler return signals.
   - Patterns: Controller for special terminal paths, Facade over artifact/metrics/review side effects, Factory-style degraded mock review payload.
   - Scheduler now delegates these paths and only applies the returned status/event/policy-learning signal.
   - Tests: `tests/test_terminal_handlers.py`.
   - Next: apply the same terminal-handler boundary to stale worker reaping if the reaper grows more artifact-writing behavior.

4g. **Stale worker reaper**
   - Implemented in `orchestrator/stale_worker_reaper.py`.
   - Owns stale heartbeat detection, dead-process detection, recoverable read-only stream salvage, process control artifact updates, and stale terminal artifact writes.
   - Patterns: Controller for recovery workflow, Facade over process/control artifact writes, Strategy injection for `pid_alive`, `now`, and `task_requires_diff`.
   - Scheduler now delegates stale-worker decisions and only writes the returned status event.
   - Tests: `tests/test_stale_worker_reaper.py` plus existing scheduler reaper integration test.
   - Next: extract task artifact repair into a repair service if repair logic continues to grow.

4h. **Task artifact repair service**
   - Implemented in `orchestrator/task_artifact_repair.py`.
   - Owns conservative repair for DB-to-`task.json` sync and OpenCode generic-summary backfill from worker stream artifacts.
   - Patterns: Information Expert for repairable artifact drift, Facade over artifact writes and repaired metrics refresh.
   - Scheduler now delegates `repair_task_artifacts(...)` and lifecycle task-artifact syncing to this service.
   - Tests: `tests/test_task_artifact_repair.py` plus existing scheduler repair integration test.
   - Next: extract outcome recording if outcome derivation needs more artifact IO or quality-matrix policy.

4i. **Task outcome recorder**
   - Implemented in `orchestrator/task_outcome_recording.py`.
   - Owns terminal artifact reads, quality outcome derivation, `task_outcomes` persistence, and `outcome.json` writes.
   - Patterns: Information Expert for quality-matrix evidence gathering, Facade over DB/artifact persistence.
   - Scheduler lifecycle now receives `TaskOutcomeRecorder.record_task_outcome` directly as the outcome callback.
   - Tests: `tests/test_task_outcome_recording.py`.
   - Next: review remaining scheduler responsibilities around Codex usage recording and world-plan creation.

4j. **Codex usage recorder**
   - Implemented in `orchestrator/codex_usage_recording.py`.
   - Owns planning-dispatch and world-review usage event construction, DB persistence, `codex_usage/*.json` artifacts, audit events, and token-ledger refresh callbacks.
   - Patterns: Facade over usage accounting side effects, Information Expert for Codex quota attribution metadata.
   - Scheduler now delegates planning dispatch usage and review usage recording to `CodexUsageRecorder`.
   - Tests: `tests/test_codex_usage_recording.py`.
   - Next: split World setup / world-plan creation out of scheduler or extract task submission construction.

4k. **World runtime service**
   - Implemented in `orchestrator/world_runtime_service.py`.
   - Owns external RuntimeStore bootstrap, World project profile wrapper, WorldPlan creation, World runtime doctor, and plan-route/safe-parallelism helpers.
   - Patterns: Facade over World setup/planning operations, Strategy injection for profiling, project detection, metrics history, and run-id generation.
   - Scheduler now exposes the same public CLI/MCP methods but delegates the implementation to `WorldRuntimeService`.
   - Tests: `tests/test_world_runtime_service.py` plus existing `test_world_tools.py` and `test_world_cli.py`.
   - Next: extract task submission construction or current-project submission lookup.

4l. **Task submission builder**
   - Implemented in `orchestrator/task_submission.py`.
   - Owns normalized task payload construction, execution protocol normalization, project-memory injection, image defaults, auto-PR policy, and route override shape.
   - Patterns: Builder for task construction, Information Expert for submission payload consistency.
   - Scheduler now creates task IDs/run dirs and persists the returned task, but no longer assembles the task dictionary inline.
   - Tests: `tests/test_task_submission.py`.
   - Next: consider extracting current-project detection and submit facade if `submit_current_project_task` grows more policy.

4m. **Approval policy service**
   - Implemented in `orchestrator/approval_policy_service.py`.
   - Owns dynamic approval decisions, learned-rule listing/revocation, policy suggestion actions, approval explanations, and user approval/rejection outcome recording.
   - Patterns: Facade over `ApprovalGraph` / `ApprovalMemory` / `PolicyUpdateEngine`, Information Expert for approval-policy persistence and explanations.
   - Scheduler now preserves the public CLI/MCP methods and execution-state transitions, but delegates approval-policy details to the service.
   - Tests: `tests/test_approval_policy_service.py` plus existing dynamic approval and scheduler coverage.
   - Next: extract `_execute` risk/approval gate into a small execution-phase object once route/run/verify tail has fewer direct scheduler dependencies.

4n. **Task route planner**
   - Implemented in `orchestrator/task_route_planner.py`.
   - Owns canonical route construction for ordinary and World-enabled tasks, route override application, WorldPlan artifact persistence, and read-budget route projection for World plans.
   - Patterns: Facade over router / WorldPlan / route override policy, Information Expert for route artifact shape.
   - Scheduler now calls `route_planner.route_for_task(...)` directly during execution and no longer imports router or World route helpers.
   - Tests: `tests/test_task_route_planner.py` plus existing scheduler and World tools coverage.
   - Next: split retry-attempt sequencing or static risk/approval gating out of `_execute`.

4o. **Task execution gate**
   - Implemented in `orchestrator/task_execution_gate.py`.
   - Owns task-type classification, static risk evaluation, dynamic approval decisioning, risk/approval artifact writes, approval explanation artifact writes, and pre-route status transition planning.
   - Patterns: Facade over risk policy and approval policy, Controller for the pre-route execution gate, Command-style `StatusTransition` results for scheduler application.
   - Scheduler now applies returned gate transitions and no longer imports `evaluate_task` or `ApprovalMode`.
   - Tests: `tests/test_task_execution_gate.py` plus existing scheduler, risk policy, and approval policy coverage.
   - Next: split retry-attempt sequencing from `_execute` so worker attempt decisions can be tested without the full scheduler.

4p. **Task attempt runner**
   - Implemented in `orchestrator/task_attempt_runner.py`.
   - Owns retry-chain construction, worker attempt execution sequencing, post-attempt decision interpretation, retry event emission, final worker-result selection, and terminal attempt failure signals.
   - Patterns: Controller for worker-attempt workflow, Strategy composition over retry-chain and post-attempt policies, Command-style terminal result for scheduler continuation.
   - Scheduler now delegates the retry loop and only handles the returned terminal status or continues into degraded/verify/review/publish.
   - Tests: `tests/test_task_attempt_runner.py` plus existing scheduler, worker-attempt executor, and post-attempt policy coverage.
   - Next: split the verify/review/publish continuation into a tail pipeline object so `_execute` becomes gate -> route -> worktree -> attempts -> tail.

4q. **Task completion pipeline**
   - Implemented in `orchestrator/task_completion_pipeline.py`.
   - Owns the post-attempt tail: degraded mock handling, verification, read-only completion, Codex review, policy-learning checkpoints, final markdown writes, and publish delegation.
   - Patterns: Pipeline / Controller for completion flow, Facade over terminal / verify / review / publish runners, Command-style status application through injected callbacks.
   - Scheduler now delegates the full completion tail and `_execute` is reduced to gate -> route -> worktree/multimodal setup -> attempts -> completion pipeline.
   - Tests: `tests/test_task_completion_pipeline.py` plus existing scheduler, terminal handler, verification, review, and publish coverage.
   - Next: extract worktree and multimodal setup into a preparation service, then review whether remaining scheduler wrappers are thin enough to keep.

4r. **Task preparation service**
   - Implemented in `orchestrator/task_preparation.py`.
   - Owns worktree creation, `worktree.json` persistence, worktree-ready status, optional MiMo vision observation injection, `task.json` refresh for vision context, and primary OpenCode AGENTS.md preparation.
   - Patterns: Facade over worktree / multimodal / AGENTS setup, Controller for pre-attempt preparation, Strategy injection for worktree and vision adapters.
   - Scheduler now delegates preparation and `_execute` reads as gate -> route -> preparation -> attempts -> completion pipeline.
   - Tests: `tests/test_task_preparation.py` plus existing scheduler, MiMo vision, and AGENTS.md coverage.
   - Next: perform a scheduler ownership audit and decide whether remaining public wrappers should stay as API facade methods or move behind smaller services.

4s. **Task operations service**
   - Implemented in `orchestrator/task_operations.py`.
   - Owns task status/result reads, baseline recording, artifact opening/repair delegation, process control reads, cancellation, and rollback.
   - Patterns: Facade for task operation API, Information Expert for task artifact/result shape, Controller for user-triggered cancel/rollback commands.
   - Scheduler keeps the public CLI/MCP-compatible methods but delegates the operation behavior to `TaskOperationsService`.
   - Tests: `tests/test_task_operations.py` plus existing baseline, scheduler, CLI, and Console coverage.
   - Next: move current-project submission/project-command wrappers behind narrower facades if scheduler remains above the target size after the execution pipeline cleanup.

4t. **Project command service**
   - Implemented in `orchestrator/project_command_service.py`.
   - Owns the scheduler-facing facade for project scan, discovery, profiling, registration, refresh, pending confirmation, confirmation, and ignore commands.
   - Patterns: Facade over Adaptive Project Layer command handlers, Controller for project registry command dispatch.
   - Scheduler still exposes the same public CLI/MCP methods but no longer imports every individual project command handler.
   - Tests: `tests/test_project_command_service.py` plus existing project discovery, registry, CLI, and MCP-facing coverage.
   - Next: extract current-project task submission if `submit_current_project_task` and `submit_task` remain the largest non-execution responsibilities.

4u. **Project lookup service**
   - Implemented in `orchestrator/project_lookup_service.py`.
   - Owns project list filtering, detect-project response shaping, and registered-project health diagnostics.
   - Patterns: Information Expert for project lookup/health rules, Facade over registry detection.
   - Scheduler delegates `list_projects(...)` and `detect_project(...)` while keeping CLI/MCP-compatible method names.
   - Tests: `tests/test_project_lookup_service.py` plus existing project registry and CLI coverage.
   - Next: extract task submission persistence so scheduler no longer creates task DB rows and dispatch usage events directly.

4v. **Task submission service**
   - Implemented in `orchestrator/task_submission_service.py`.
   - Owns project lookup for submission, task id/run dir allocation, submission payload persistence, task DB row creation, created events, and Codex planning-dispatch usage recording.
   - Patterns: Controller for submit-task workflow, Facade over builder / DB / artifact / usage side effects.
   - Scheduler delegates `submit_task(...)` and only supplies execution/status callbacks to keep the public API compatible.
   - Tests: `tests/test_task_submission_service.py` plus existing task submission, scheduler, CLI, and World coverage.
   - Next: extract current-project submission detection or reduce `_execute` further if scheduler remains above target size.

4w. **Current project task service**
   - Implemented in `orchestrator/current_project_task_service.py`.
   - Owns current-repository project detection, NEEDS_USER response shaping when detection fails, and delegation into the normal submit-task path.
   - Patterns: Controller for current-project task submission, Facade over project detection and task submission.
   - Scheduler delegates `submit_current_project_task(...)` while keeping MCP-compatible public parameters.
   - Tests: `tests/test_current_project_task_service.py` plus existing MCP/scheduler submission coverage.
   - Next: reduce remaining scheduler helper wrappers or assess whether `_execute` is now the only substantial orchestration logic left.

4x. **Task execution service**
   - Implemented in `orchestrator/task_execution_service.py`.
   - Owns the post-submission execution pipeline: execution gate application, route artifact and DB route fields, preparation, attempt runner results, terminal attempt policy signals, and completion pipeline handoff.
   - Patterns: Pipeline / Controller for execution orchestration, Facade over gate / route / preparation / attempts / completion collaborators.
   - Scheduler keeps `_execute(...)` as an internal compatibility facade and delegates the real behavior to `TaskExecutionService`.
   - Tests: `tests/test_task_execution_service.py` plus existing scheduler, gate, route, attempt, preparation, and completion tests.
   - Next: scheduler is now mostly API facade plus composition root; review remaining helper wrappers for whether they are stable callback adapters or should move into a composition module.

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
