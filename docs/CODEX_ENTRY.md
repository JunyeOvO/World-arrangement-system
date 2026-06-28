# World Codex Entry

Codex is World Entry and World Review. Users interact with Codex; Codex calls World Core through MCP tools.

## Trigger Phrases

- `本项目开发使用 World 系统`
- `use World system`
- `World 系统接管`
- `World 多层编排`
- `使用 World Orchestrator`

## Entry Flow

```text
User prompt
  -> Codex recognizes World trigger
  -> world_bootstrap
  -> world_profile_project
  -> world_create_plan
  -> worker dispatch through World Core
  -> verification
  -> final_review_packet
  -> Codex World Review
```

## MCP Tools

World-named tools:

- `world_bootstrap`
- `world_profile_project`
- `world_create_plan`
- `world_doctor`

Compatibility tools remain available:

- `list_projects`
- `detect_project`
- `submit_task`
- `submit_current_project_task`
- `get_task_status`
- `read_task_result`
- `cancel_task`
- `rollback_task`
- `open_task_artifacts`

## Hard Rules

- Do not copy World core files into business repos.
- Use `zero_write` by default.
- Use `ignored_write` only when external runtime storage is unavailable.
- Do not directly modify main/master.
- Do not auto-merge.
- Do not force push.
- Do not bypass World Guard.
