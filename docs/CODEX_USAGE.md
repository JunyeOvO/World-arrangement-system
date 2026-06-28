# Codex Usage

After registering the MCP server, Codex should see:

- `list_projects`
- `detect_project`
- `submit_task`
- `submit_current_project_task`
- `get_task_status`
- `read_task_result`
- `cancel_task`
- `rollback_task`
- `open_task_artifacts`

Prefer `submit_current_project_task` when working inside a registered repository. Prefer explicit `submit_task` when the target project is known.

Always inspect `read_task_result` before summarizing to the user.

