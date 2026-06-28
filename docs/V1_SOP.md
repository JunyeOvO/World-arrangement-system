# V1 SOP

1. Run `uv run ai-dispatcher doctor`.
2. Ensure `~/.ai-orchestrator/projects.yaml` points to real repos.
3. If WSL worker commands have non-default names, export `AI_CLAUDE_CMD` and `AI_OPENCODE_CMD`.
4. Submit a dry-run task.
5. Inspect `~/.ai-orchestrator/runs/<task_id>/`.
6. Enable real workers only after provider env profiles are configured.
7. Enable PR publishing only after `gh auth status` passes and `allow_remote_push=true`.

V1 never auto-merges. Merge decisions remain human-only.

## Running DeepSeek and MiMo Through Claude Code

Do not switch global Claude settings between providers while tasks are running.

Use `models.yaml` to bind each logical model to its own `env_profile`. The orchestrator loads that profile per subprocess, so DeepSeek and MiMo tasks can run independently without sharing provider state.
