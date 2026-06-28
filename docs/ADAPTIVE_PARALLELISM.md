# World Adaptive Parallelism

World 并行不是开更多 Worker，而是在文件所有权、冲突风险、测试成本和安全策略允许的范围内拆分任务。

## Scheduler Principles

- Each Worker runs in an isolated git worktree.
- Each Worker receives `owned_paths`, `readonly_paths`, and `forbidden_paths`.
- Shared hot files are serialized or escalated for review.
- Patches must pass `git apply --check` before merge.
- Verification runs after merge.
- Codex performs World Review before PR creation.
- No Worker may push, merge, force push, or bypass permissions.

## Parallelism Formula

```text
parallelism = min(
  user_max_parallelism,
  project_safe_parallelism,
  task_split_count,
  available_worker_count,
  token_budget_limit,
  test_cost_limit,
  conflict_risk_limit
)
```

## Default Safe Parallelism

| Project / Task | Safe Parallelism |
|---|---:|
| Docs / README / tests | 4-8 |
| Frontend app | 3-5 |
| Node / Python backend | 2-4 |
| Android / Gradle | 1-2 |
| Java / compiler / course labs | 1-2 |
| Unity / Blender / asset project | 1 |
| Auth / payment / database / production config | 1 |

## Conflict Risk Signals

Hot files:

- `package.json`
- lock files
- `pyproject.toml`
- Gradle/Maven/Cargo manifests
- Docker and Compose files
- CI/CD config
- auth/payment/router config
- database migrations

High-risk signals force serial execution or hard approval.
