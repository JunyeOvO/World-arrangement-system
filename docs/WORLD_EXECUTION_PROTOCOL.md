# World Explicit Execution Protocol

World tasks should carry explicit execution fields instead of relying only on natural-language inference.

## Fields

```yaml
task_mode: read_only | patch | test | docs | audit
expected_diff: true | false
verification_policy: none | changed_files_only | unit | full
read_budget_profile: quick_triage | code_contract_audit | next_task_planning | docs_review
read_budget:
  max_files: 8
  max_dirs: 3
  max_worker_turns: 8
  max_duration_sec: 900
  max_output_tokens: 4000
```

## Semantics

- `task_mode`: the intended task class.
- `expected_diff`: whether the worker is expected to modify files.
- `verification_policy`:
  - `none`: run no project verification commands.
  - `changed_files_only`: check changed files and forbidden paths, but run no project test/build commands.
  - `unit`: run the first configured test command only.
  - `full`: run all configured test and build commands.
- `read_budget_profile`: named budget defaults for common task shapes.
- `read_budget.max_worker_turns`: passed to workers that support turn limits.
- `read_budget.max_duration_sec`: passed to worker process timeout.
- `read_budget.max_files`, `max_dirs`, and `max_output_tokens`: included in the worker prompt as hard budget guidance.

Named profiles:

| Profile | Files | Dirs | Turns | Timeout | Output | Use |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `quick_triage` | 6 | 2 | 6 | 90s | 2500 | Fast bounded checks. |
| `code_contract_audit` | 10 | 4 | 10 | 150s | 4000 | Cross-file contracts and architecture/data-flow checks. |
| `next_task_planning` | 14 | 5 | 14 | 210s | 4500 | Selecting next implementation candidates. |
| `docs_review` | 6 | 2 | 6 | 90s | 3000 | README/docs onboarding and documentation gaps. |

Explicit `read_budget.*` values override the selected profile for that task.

For read-only tasks, World now instructs workers to emit a concise partial result before exhausting the read budget. If a worker still stops with `max_turns_no_diff` or `worker_no_diff`, the scheduler can salvage a meaningful assistant partial result as a read-only artifact instead of discarding the run.

## CLI Example

```powershell
uv run ai-dispatcher submit-task `
  --project travel_with_me `
  --risk-level low `
  --worker claude_code `
  --model deepseek_flash `
  --task-mode read_only `
  --expected-diff false `
  --verification-policy changed_files_only `
  --read-budget-profile code_contract_audit `
  --read-budget max_files=8 `
  --read-budget max_worker_turns=6 `
  --read-budget max_duration_sec=90 `
  --goal "只读判断 3D workArea 数据契约风险，输出最小修复入口，changed_files=[]。"
```

## Template Example

The same fields may be placed at the top of a `/world` task body:

```text
project: travel_with_me
mode: execute
world_preflight: minimal
world_self_analysis: false
task_mode: read_only
expected_diff: false
verification_policy: changed_files_only
read_budget_profile: code_contract_audit
read_budget.max_files: 8
read_budget.max_worker_turns: 6
read_budget.max_duration_sec: 90
read_budget.max_output_tokens: 3000

请直接执行项目任务，不要分析 World 系统本身。
目标：只读判断 3D workArea 数据契约风险。
验收标准：输出关键数据流、最可能断点、最小修复入口、changed_files=[]。
安全约束：不读不输出 secrets；不自动 merge；不自动 PR。
```

## Default Policy

When fields are omitted, World still infers conservative defaults:

- Read-only or audit-like goals default to `task_mode=read_only`, `expected_diff=false`, `verification_policy=changed_files_only`.
- Test-like goals default to `task_mode=test`, `verification_policy=unit`.
- Patch-like goals default to `task_mode=patch`, `expected_diff=true`, `verification_policy=full`.
- Budget profiles are inferred when omitted: docs goals use `docs_review`, cross-file contract/architecture goals use `code_contract_audit`, next-task planning goals use `next_task_planning`, and other tasks use `quick_triage`.

Explicit fields always win over natural-language inference.
