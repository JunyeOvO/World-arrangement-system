# World Worker Contract

Every Worker receives a structured task, runs in an isolated worktree, and returns a structured result. Worker output is reviewed by World Core and Codex World Review before PR creation.

## WorkerTask

Required fields:

- `task_id`
- `run_id`
- `worker_type`
- `model_policy`
- `goal`
- `repo_worktree_path`
- `owned_paths`
- `readonly_paths`
- `forbidden_paths`
- `commands_allowed`
- `commands_forbidden`

## WorkerResult

Required fields:

- `status`
- `summary`
- `changed_files`
- `patch_file`
- `tests_run`
- `risks`
- `rollback_notes`

## Provider Rules

Claude Code agent:

- Allowed LLMs: DeepSeek V4 flash, DeepSeek V4 pro, MiMo V2.5, MiMo V2.5 pro
- Forbidden providers: GLM, GLM-5.2, Z.AI GLM, ChatGLM

OpenCode agent:

- Only GLM 5.2 route
- Model: `opencode-go/glm-5.2`
- Legal variants: `high`, `max`, `minimal`
- `default` means omit `--variant`

Codex agent:

- Only World Review route
- LLM: GPT 5.5

There is no independent MiMo worker in the current router. MiMo V2.5 and MiMo V2.5 pro run through Claude Code.

## Forbidden Actions

- `git push`
- `git push --force`
- `git merge`
- `git rebase`
- `gh pr merge`
- destructive deletes
- production database destructive operations
- `--dangerously-skip-permissions`
- reading or modifying `.env`, keys, credentials, or secrets
