from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ensure_runtime_dirs, paths
from .constants import DEFAULT_CLAUDE_CMD, DEFAULT_OPENCODE_CMD
from .command_utils import command_available
from .scheduler import OrchestratorService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-dispatcher",
        description="World CLI — World System command-line interface",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    serve_console = sub.add_parser("serve-console")
    serve_console.add_argument("--host", default="127.0.0.1")
    serve_console.add_argument("--port", type=int, default=8765)
    world_doctor = sub.add_parser("world-doctor")
    world_doctor.add_argument("--repo-path", default=None)
    world_bootstrap = sub.add_parser("world-bootstrap")
    world_bootstrap.add_argument("--repo-path", required=True)
    world_bootstrap.add_argument("--prompt", default="本项目开发使用 World 系统")
    world_bootstrap.add_argument("--write-policy", default="zero_write")
    world_plan = sub.add_parser("world-create-plan")
    world_plan.add_argument("--repo-path", required=True)
    world_plan.add_argument("--goal", required=True)
    world_plan.add_argument("--risk-level", default="medium")
    world_plan.add_argument("--write-policy", default="zero_write")
    sub.add_parser("list-projects")
    detect = sub.add_parser("detect-project")
    detect.add_argument("--repo-path", default=".")
    submit = sub.add_parser("submit-task")
    submit.add_argument("--project", required=True)
    submit.add_argument("--goal", required=True)
    submit.add_argument("--risk-level", default="medium")
    submit.add_argument("--auto-pr", action="store_true")
    submit.add_argument("--no-execute", action="store_true")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--worker", default=None, help="Force a worker for this task, e.g. opencode")
    submit.add_argument("--model", default=None, help="Force a model for this task, e.g. opencode-go/glm-5.2")
    submit.add_argument("--variant", default=None, help="Force a capability/CLI variant for this task, e.g. high or max")
    submit.add_argument("--image-path", action="append", default=[], help="Local PNG/JPEG path for MiMo vision observation")
    submit.add_argument("--image-base64", action="append", default=[], help="Inline base64 PNG/JPEG or data URL for MiMo vision observation")
    status = sub.add_parser("get-task-status")
    status.add_argument("--task-id", required=True)
    result = sub.add_parser("read-task-result")
    result.add_argument("--task-id", required=True)
    artifacts = sub.add_parser("open-task-artifacts")
    artifacts.add_argument("--task-id", required=True)
    control = sub.add_parser("get-task-control")
    control.add_argument("--task-id", required=True)
    cancel = sub.add_parser("cancel-task")
    cancel.add_argument("--task-id", required=True, help="Task ID to cancel")
    cancel.add_argument("--reason", default="", help="Reason for cancellation")
    rollback = sub.add_parser("rollback-task")
    rollback.add_argument("--task-id", required=True, help="Task ID to rollback")
    rollback.add_argument("--no-cleanup", action="store_true", help="Keep worktree")
    args = parser.parse_args(argv)

    service = OrchestratorService()
    if args.cmd == "doctor":
        return _doctor()
    if args.cmd == "serve-console":
        from .console.app import main as console_main
        return console_main(["--host", args.host, "--port", str(args.port)])
    if args.cmd == "world-doctor":
        return _print(service.world_doctor(args.repo_path))
    if args.cmd == "world-bootstrap":
        return _print(service.world_bootstrap(args.repo_path, args.prompt, args.write_policy))
    if args.cmd == "world-create-plan":
        return _print(service.world_create_plan(args.repo_path, args.goal, args.risk_level, args.write_policy))
    if args.cmd == "list-projects":
        return _print(service.list_projects())
    if args.cmd == "detect-project":
        return _print(service.detect_project(repo_path=args.repo_path))
    if args.cmd == "submit-task":
        return _print(
            service.submit_task(
                args.project,
                args.goal,
                args.risk_level,
                not args.no_execute,
                args.auto_pr,
                args.dry_run,
                args.worker,
                args.model,
                args.variant,
                args.image_path,
                args.image_base64,
            )
        )
    if args.cmd == "get-task-status":
        return _print(service.get_task_status(args.task_id))
    if args.cmd == "read-task-result":
        return _print(service.read_task_result(args.task_id))
    if args.cmd == "open-task-artifacts":
        return _print(service.open_task_artifacts(args.task_id))
    if args.cmd == "get-task-control":
        return _print(service.get_task_control(args.task_id))
    if args.cmd == "cancel-task":
        result = service.cancel_task(args.task_id, reason=args.reason)
        _print(result)
        return 0 if result.get("status") != "NOT_FOUND" else 1
    if args.cmd == "rollback-task":
        result = service.rollback_task(args.task_id, cleanup_worktree=not args.no_cleanup)
        _print(result)
        return 0 if result.get("status") != "NOT_FOUND" else 1
    return 2


def _print(payload: object) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _doctor() -> int:
    p = ensure_runtime_dirs()
    report: list[tuple[str, bool, str]] = []
    report.append(("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]))
    command_map = {
        "git": "git",
        "codex": "codex",
        "opencode": os.environ.get("AI_OPENCODE_CMD", DEFAULT_OPENCODE_CMD),
        "claude": os.environ.get("AI_CLAUDE_CMD", DEFAULT_CLAUDE_CMD),
        "gh": "gh",
        "uv": "uv",
    }
    for label, binary in command_map.items():
        ok, detail = command_available(binary)
        report.append((f"{label} available", ok, detail))
    report.append(("runtime home exists", p.home.exists(), str(p.home)))
    report.append(("projects.yaml exists", p.projects_yaml.exists(), str(p.projects_yaml)))
    report.append(("models.yaml exists", p.models_yaml.exists(), str(p.models_yaml)))
    report.append(("policies.yaml exists", p.policies_yaml.exists(), str(p.policies_yaml)))
    text = "\n".join(f"- [{'x' if ok else ' '}] {name}: {detail}" for name, ok, detail in report)
    doctor_path = paths().home / "doctor-report.md"
    doctor_path.write_text("# Doctor Report\n\n" + text + "\n", encoding="utf-8")
    print(doctor_path.read_text(encoding="utf-8"))
    return 0 if all(ok for _, ok, _ in report[:1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
