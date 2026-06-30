from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .artifacts import ArtifactStore
from .approval_policy_service import ApprovalPolicyService
from .attempt_recording import AttemptMetricsRecorder
from .codex_usage_recording import CodexUsageRecorder
from .config import ensure_runtime_dirs
from .current_project_task_service import CurrentProjectTaskService
from .db import TaskDB
from .execution_callbacks import ExecutionCallbackAdapter
from .policy_learning import PolicyLearningRecorder
from .project_command_service import ProjectCommandService
from .project_lookup_service import ProjectLookupService
from .stale_worker_reaper import StaleWorkerReaper
from .task_artifact_repair import TaskArtifactRepairService
from .task_attempt_runner import TaskAttemptRunner
from .task_completion_pipeline import TaskCompletionPipeline
from .task_execution_gate import TaskExecutionGate
from .task_execution_service import TaskExecutionService
from .task_lifecycle import TaskLifecycleController
from .task_operations import TaskOperationsService
from .task_outcome_recording import TaskOutcomeRecorder
from .task_preparation import TaskPreparationService
from .task_publish import TaskPublishRunner
from .task_review import TaskReviewRunner
from .task_route_planner import TaskRoutePlanner
from .task_submission import TaskSubmissionBuilder
from .task_submission_service import TaskSubmissionService
from .task_verification import TaskVerificationRunner
from .terminal_handlers import TerminalTaskHandler
from .verifier import VerifyResult
from .worker_permission_audit import WorkerPermissionAuditor
from .worker_attempt_executor import WorkerAttemptExecutor
from .workers.base import Worker
from .world_runtime_service import WorldRuntimeService


@dataclass
class OrchestratorComponents:
    paths: Any
    db: TaskDB
    artifacts: ArtifactStore
    project_lookup: ProjectLookupService
    project_commands: ProjectCommandService
    attempt_metrics: AttemptMetricsRecorder
    permission_auditor: WorkerPermissionAuditor
    submission_builder: TaskSubmissionBuilder
    artifact_repair: TaskArtifactRepairService
    outcome_recorder: TaskOutcomeRecorder
    codex_usage: CodexUsageRecorder
    world_runtime: WorldRuntimeService
    route_planner: TaskRoutePlanner
    lifecycle: TaskLifecycleController
    stale_worker_reaper: StaleWorkerReaper
    policy_learning: PolicyLearningRecorder
    execution_callbacks: ExecutionCallbackAdapter
    preparation: TaskPreparationService
    attempt_executor: WorkerAttemptExecutor
    attempt_runner: TaskAttemptRunner
    verification_runner: TaskVerificationRunner
    review_runner: TaskReviewRunner
    publish_runner: TaskPublishRunner
    terminal_handler: TerminalTaskHandler
    completion_pipeline: TaskCompletionPipeline
    approval_policy: ApprovalPolicyService
    execution_gate: TaskExecutionGate
    task_execution: TaskExecutionService
    task_submission: TaskSubmissionService
    current_project_tasks: CurrentProjectTaskService
    task_operations: TaskOperationsService


def build_orchestrator_components(
    *,
    profile_project: Callable[..., dict[str, Any]],
    detect_project: Callable[..., dict[str, Any]],
    world_create_plan: Callable[..., dict[str, Any]],
    submit_task: Callable[..., dict[str, Any]],
    execute_task: Callable[..., None],
    get_task_status: Callable[[str], dict[str, Any]],
    new_task_id: Callable[[], str],
    now: Callable[[], str],
    dry_verify_func: Callable[[dict[str, Any]], VerifyResult],
    task_requires_diff: Callable[[dict[str, Any]], bool],
    verify_func: Callable[..., VerifyResult],
    review_func: Callable[..., dict[str, Any]],
    publish_func: Callable[..., dict[str, Any]],
    build_prompt: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], str],
    workers: dict[str, Worker],
    default_worker: Worker,
) -> OrchestratorComponents:
    paths = ensure_runtime_dirs()
    db = TaskDB(paths.state_db)
    db.init()
    artifacts = ArtifactStore(paths.runs)
    project_lookup = ProjectLookupService()
    project_commands = ProjectCommandService()
    attempt_metrics = AttemptMetricsRecorder(db)
    permission_auditor = WorkerPermissionAuditor(db)
    submission_builder = TaskSubmissionBuilder()
    artifact_repair = TaskArtifactRepairService(
        db=db,
        artifacts=artifacts,
        metrics_recorder=attempt_metrics,
    )
    outcome_recorder = TaskOutcomeRecorder(db=db, artifacts=artifacts)
    codex_usage = CodexUsageRecorder(
        db=db,
        artifacts=artifacts,
        write_token_ledger=attempt_metrics.write_token_ledger,
    )
    world_runtime = WorldRuntimeService(
        profile_project=profile_project,
        detect_project=detect_project,
        model_metrics_summary=db.model_metrics_summary,
        new_run_id=new_task_id,
    )
    route_planner = TaskRoutePlanner(
        artifacts=artifacts,
        model_metrics_summary=db.model_metrics_summary,
        world_plan_factory=world_create_plan,
    )
    lifecycle = TaskLifecycleController(
        db,
        now=now,
        sync_task_artifact=artifact_repair.sync_task_artifact_from_db,
        record_task_outcome=outcome_recorder.record_task_outcome,
    )
    stale_worker_reaper = StaleWorkerReaper(
        artifacts=artifacts,
        dry_verify_func=dry_verify_func,
        task_requires_diff=task_requires_diff,
    )
    policy_learning = PolicyLearningRecorder(db)
    execution_callbacks = ExecutionCallbackAdapter(
        lifecycle=lifecycle,
        policy_learning=policy_learning,
        permission_auditor=permission_auditor,
        attempt_metrics=attempt_metrics,
        stale_worker_reaper=stale_worker_reaper,
    )
    preparation = TaskPreparationService(
        artifacts=artifacts,
        set_status=execution_callbacks.set_status,
    )
    attempt_executor = WorkerAttemptExecutor(
        artifacts=artifacts,
        permission_auditor=permission_auditor,
        metrics_recorder=attempt_metrics,
        workers=workers,
        default_worker=default_worker,
        now=now,
        set_status=execution_callbacks.set_status,
        build_prompt=build_prompt,
    )
    attempt_runner = TaskAttemptRunner(
        artifacts=artifacts,
        attempt_executor=attempt_executor,
        workers=workers,
        default_worker=default_worker,
        set_status=execution_callbacks.set_status,
        write_attempt_metrics=execution_callbacks.write_attempt_metrics,
    )
    verification_runner = TaskVerificationRunner(
        artifacts=artifacts,
        verify_func=verify_func,
        dry_verify_func=dry_verify_func,
    )
    review_runner = TaskReviewRunner(
        review_func=review_func,
        record_codex_usage=codex_usage.record_review_usage,
    )
    publish_runner = TaskPublishRunner(
        artifacts=artifacts,
        db=db,
        publish_func=publish_func,
        now=now,
    )
    terminal_handler = TerminalTaskHandler(
        artifacts=artifacts,
        metrics_recorder=attempt_metrics,
        dry_verify_func=dry_verify_func,
        record_review_codex_usage=codex_usage.record_review_usage,
    )
    completion_pipeline = TaskCompletionPipeline(
        artifacts=artifacts,
        terminal_handler=terminal_handler,
        verification_runner=verification_runner,
        review_runner=review_runner,
        publish_runner=publish_runner,
        set_status=execution_callbacks.set_status,
        record_policy_learning=execution_callbacks.record_policy_learning,
        write_attempt_metrics=execution_callbacks.write_attempt_metrics,
    )
    approval_policy = ApprovalPolicyService(db)
    execution_gate = TaskExecutionGate(
        artifacts=artifacts,
        approval_policy=approval_policy,
    )
    task_execution = TaskExecutionService(
        db=db,
        artifacts=artifacts,
        execution_gate=execution_gate,
        route_planner=route_planner,
        preparation=preparation,
        attempt_runner=attempt_runner,
        completion_pipeline=completion_pipeline,
        set_status=execution_callbacks.set_status,
        record_policy_learning=execution_callbacks.record_policy_learning,
        now=now,
    )
    task_submission = TaskSubmissionService(
        db=db,
        artifacts=artifacts,
        submission_builder=submission_builder,
        codex_usage=codex_usage,
        new_task_id=new_task_id,
        now=now,
        execute_task=execute_task,
        get_task_status=get_task_status,
    )
    current_project_tasks = CurrentProjectTaskService(
        submit_task=submit_task,
    )
    task_operations = TaskOperationsService(
        db=db,
        artifacts=artifacts,
        artifact_repair=artifact_repair,
        reap_stale_worker_task=execution_callbacks.reap_stale_worker_task,
        record_policy_learning=execution_callbacks.record_policy_learning,
        write_token_ledger=execution_callbacks.write_token_ledger,
        now=now,
    )
    return OrchestratorComponents(
        paths=paths,
        db=db,
        artifacts=artifacts,
        project_lookup=project_lookup,
        project_commands=project_commands,
        attempt_metrics=attempt_metrics,
        permission_auditor=permission_auditor,
        submission_builder=submission_builder,
        artifact_repair=artifact_repair,
        outcome_recorder=outcome_recorder,
        codex_usage=codex_usage,
        world_runtime=world_runtime,
        route_planner=route_planner,
        lifecycle=lifecycle,
        stale_worker_reaper=stale_worker_reaper,
        policy_learning=policy_learning,
        execution_callbacks=execution_callbacks,
        preparation=preparation,
        attempt_executor=attempt_executor,
        attempt_runner=attempt_runner,
        verification_runner=verification_runner,
        review_runner=review_runner,
        publish_runner=publish_runner,
        terminal_handler=terminal_handler,
        completion_pipeline=completion_pipeline,
        approval_policy=approval_policy,
        execution_gate=execution_gate,
        task_execution=task_execution,
        task_submission=task_submission,
        current_project_tasks=current_project_tasks,
        task_operations=task_operations,
    )
