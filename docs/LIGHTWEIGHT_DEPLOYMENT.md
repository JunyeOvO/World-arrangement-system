# World Lightweight Deployment

World 系统默认作为项目外控制面运行。业务仓库不承载 World 核心文件，运行态写入外部 RuntimeStore。

## Write Policies

| Policy | Behavior |
|---|---|
| `zero_write` | Default. All runtime files go to `~/.world/projects/<repo_hash>/` or temp fallback. The business repo stays clean. |
| `ignored_write` | Fallback only. Runtime may go to `<repo>/.world/`, and World writes ignore rules to `.git/info/exclude`. |
| `adapter_file` | Requires explicit approval. Only tiny adapter files such as `AGENTS.md` or `world.project.json` are allowed. |
| `full_project_mode` | Disabled by default. Requires explicit user request. |

## RuntimeStore

Implemented in `orchestrator/runtime_store.py`.

Backend order:

1. `external-global`: `~/.world/projects/<repo_hash>/`
2. `external-temp`: OS temp directory under `world-runs/<repo_hash>/`
3. `repo-local-ignored`: `<repo>/.world/` only for `ignored_write`

## IgnoreManager

Implemented in `orchestrator/ignore_manager.py`.

Rules:

- Prefer `.git/info/exclude`.
- Do not edit `.gitignore` by default.
- Add the World ignore block idempotently.
- Support removing the World ignore block for cleanup.

## Acceptance

`zero_write` acceptance:

- No `.world/` is created in the business repo.
- `git status --short` remains clean.
- `project.profile.json` and `runs/<run_id>/plan.json` are written outside the repo.

`ignored_write` acceptance:

- `.world/` is ignored through `.git/info/exclude`.
- Repeated runs do not duplicate ignore rules.
- Cleanup can remove repo-local runtime files.
