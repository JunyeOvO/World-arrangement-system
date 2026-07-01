from __future__ import annotations

from .scheduler import OrchestratorService

INSTRUCTIONS = """
Use ai_dispatcher as the single entrypoint for background coding tasks.
Never request auto-merge. Prefer submit_current_project_task when the current repo is known.
Read results with read_task_result and inspect artifacts before summarizing to the user.
"""


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("Install optional dependency: ai-orchestrator-v1[mcp]") from exc

    service = OrchestratorService()
    mcp = FastMCP("ai_dispatcher", instructions=INSTRUCTIONS)

    @mcp.tool()
    def list_projects(query: str | None = None):
        return service.list_projects(query)

    @mcp.tool()
    def detect_project(repo_path: str | None = None, git_remote_url: str | None = None, cwd: str | None = None):
        return service.detect_project(repo_path, git_remote_url, cwd)

    # ── World vNext lightweight tools ──

    @mcp.tool()
    def world_bootstrap(repo_path: str, user_prompt: str = "本项目开发使用 World 系统", preferred_write_policy: str = "zero_write"):
        return service.world_bootstrap(repo_path, user_prompt, preferred_write_policy)

    @mcp.tool()
    def world_profile_project(repo_path: str, force: bool = False):
        return service.world_profile_project(repo_path, force)

    @mcp.tool()
    def world_create_plan(repo_path: str, user_goal: str, risk_level: str = "medium", preferred_write_policy: str = "zero_write"):
        return service.world_create_plan(repo_path, user_goal, risk_level, preferred_write_policy)

    @mcp.tool()
    def world_doctor(repo_path: str | None = None):
        return service.world_doctor(repo_path)

    @mcp.tool()
    def submit_task(
        project_id: str,
        user_goal: str,
        risk_level: str = "medium",
        auto_execute: bool = True,
        auto_pr: bool = False,
        dry_run: bool = False,
        force_worker: str | None = None,
        force_model: str | None = None,
        force_variant: str | None = None,
        image_paths: list[str] | None = None,
        image_base64: list[str] | None = None,
        task_mode: str | None = None,
        expected_diff: bool | None = None,
        verification_policy: str | None = None,
        read_budget_profile: str | None = None,
        read_budget: dict | None = None,
    ):
        return service.submit_task(
            project_id,
            user_goal,
            risk_level,
            auto_execute,
            auto_pr,
            dry_run,
            force_worker,
            force_model,
            force_variant,
            image_paths=image_paths,
            image_base64=image_base64,
            task_mode=task_mode,
            expected_diff=expected_diff,
            verification_policy=verification_policy,
            read_budget_profile=read_budget_profile,
            read_budget=read_budget,
        )

    @mcp.tool()
    def submit_current_project_task(
        repo_path: str,
        user_goal: str,
        risk_level: str = "medium",
        auto_execute: bool = True,
        auto_pr: bool = False,
        dry_run: bool = False,
        force_worker: str | None = None,
        force_model: str | None = None,
        force_variant: str | None = None,
        image_paths: list[str] | None = None,
        image_base64: list[str] | None = None,
        task_mode: str | None = None,
        expected_diff: bool | None = None,
        verification_policy: str | None = None,
        read_budget_profile: str | None = None,
        read_budget: dict | None = None,
    ):
        return service.submit_current_project_task(
            user_goal,
            repo_path,
            risk_level,
            auto_execute,
            auto_pr,
            dry_run,
            force_worker,
            force_model,
            force_variant,
            image_paths=image_paths,
            image_base64=image_base64,
            task_mode=task_mode,
            expected_diff=expected_diff,
            verification_policy=verification_policy,
            read_budget_profile=read_budget_profile,
            read_budget=read_budget,
        )

    @mcp.tool()
    def get_task_status(task_id: str):
        return service.get_task_status(task_id)

    @mcp.tool()
    def read_task_result(task_id: str, sections: list[str] | None = None):
        return service.read_task_result(task_id, sections)

    @mcp.tool()
    def cancel_task(task_id: str, reason: str = ""):
        return service.cancel_task(task_id, reason)

    @mcp.tool()
    def rollback_task(task_id: str, cleanup_worktree: bool = True):
        return service.rollback_task(task_id, cleanup_worktree)

    @mcp.tool()
    def open_task_artifacts(task_id: str):
        return service.open_task_artifacts(task_id)

    # ── Dynamic Approval Graph tools ──

    @mcp.tool()
    def get_approval_decision(project_id: str, user_goal: str, risk_level: str = "medium"):
        return service.get_approval_decision(project_id, user_goal, risk_level)

    @mcp.tool()
    def approve_task(task_id: str):
        return service.approve_task(task_id)

    @mcp.tool()
    def reject_task(task_id: str, reason: str = ""):
        return service.reject_task(task_id, reason)

    @mcp.tool()
    def list_learned_rules(project_id: str):
        return service.list_learned_rules(project_id)

    @mcp.tool()
    def revoke_learned_rule(pattern_id: int):
        return service.revoke_learned_rule(pattern_id)

    @mcp.tool()
    def explain_approval(task_id: str):
        return service.explain_approval(task_id)

    @mcp.tool()
    def list_policy_suggestions(project_id: str):
        return service.list_policy_suggestions(project_id)

    @mcp.tool()
    def approve_policy_suggestion(suggestion_id: int):
        return service.approve_policy_suggestion(suggestion_id)

    @mcp.tool()
    def reject_policy_suggestion(suggestion_id: int):
        return service.reject_policy_suggestion(suggestion_id)

    # ── Adaptive Project Layer tools ──

    @mcp.tool()
    def scan_project_roots(roots: list[str] | None = None, max_depth: int = 3):
        """Scan root directories for project candidates (.git repos)."""
        return service.scan_project_roots(roots, max_depth)

    @mcp.tool()
    def discover_projects(roots: list[str] | None = None, max_depth: int = 3):
        """Scan + profile: discover projects and return full profiles with confidence scores."""
        return service.discover_projects(roots, max_depth)

    @mcp.tool()
    def profile_project(repo_path: str, force: bool = False):
        """Deep-profile a single project directory. Returns type, stack, confidence, indicators."""
        return service.profile_project(repo_path, force)

    @mcp.tool()
    def register_project(repo_path: str, confirm: bool = False):
        """Register a discovered project into projects.yaml. Set confirm=true to force registration of low-confidence projects."""
        return service.register_project(repo_path, confirm)

    @mcp.tool()
    def refresh_project_profile(project_id: str):
        """Re-profile and refresh a registered project's fingerprint and metadata."""
        return service.refresh_project_profile(project_id)

    @mcp.tool()
    def list_unregistered_projects():
        """List projects with status=pending_confirmation that need user review."""
        return service.list_unregistered_projects()

    @mcp.tool()
    def confirm_project_profile(project_id: str):
        """Confirm a pending project and move it to active status."""
        return service.confirm_project_profile(project_id)

    @mcp.tool()
    def ignore_project(repo_path: str, reason: str = ""):
        """Add a project path to the ignore list so it won't be re-discovered."""
        return service.ignore_project(repo_path, reason)

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
