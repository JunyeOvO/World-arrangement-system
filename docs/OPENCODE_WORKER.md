# World OpenCode Worker

## Current Control Boundary

OpenCode owns provider authentication and provider configuration. World does not inject API
profiles, API keys, or provider endpoint environment variables into OpenCode subprocesses.

World only controls:

- `opencode run`
- `-m opencode-go/glm-5.2`
- optional CLI variant normalization (`high|max|minimal`; `default` means omit the flag)
- worktree path, task title, prompt, stdout/stderr capture, process timeout, heartbeat, cancellation

## 定位

World OpenCode Worker 是 GLM-5.2 的**唯一**执行 Worker。ClaudeCodeWorker 不接 GLM。

> Hotpatch: GLM-5.2 is only allowed through OpenCodeWorker + opencode-go/glm-5.2.

## 为什么 GLM-5.2 只走 OpenCodeWorker

- ClaudeCodeWorker 通过 Anthropic-compatible endpoint 调用，后端限定为 DeepSeek / MiMo
- GLM-5.2 需要 OpenCode Go 的原生模型支持和 variant 机制
- 分离避免 ClaudeCodeWorker 误接 GLM

## 命令格式

```bash
opencode run \
  -m opencode-go/glm-5.2 \
  --variant <default|high|max> \
  --format json \
  --dir "$WORKTREE_DIR" \
  --title "$TASK_ID" \
  "$PROMPT"
```

### 必须参数

| 参数 | 说明 |
|------|------|
| `-m` | 模型标识 `opencode-go/glm-5.2` |
| `--variant` | 执行变体：default / high / max |
| `--format json` | JSON 输出格式 |
| `--dir` | Git worktree 目录 |
| `--title` | 任务 ID |
| PROMPT | 任务提示词（位置参数） |

### 禁止

- `--dangerously-skip-permissions` — 永久禁止
- `git push` — Worker 不推送
- `merge` — Worker 不合并
- 创建 PR — 由 Orchestrator 统一处理

## variant 策略

| variant | 使用场景 |
|---------|---------|
| **default** | 自动化保守模式 / save quota |
| **high** | 普通 GLM-5.2 请求、复杂 coding |
| **max** | 疑难 bug、二次失败升级、高风险审批后 |

### 失败升级链

```
default → high → max → Codex review / NEEDS_USER
```

禁止长期默认 max。

### CLI 与规格 variant 的映射

opencode CLI 实际只接受 `--variant` 取值为 `high | max | minimal`。规格中的 `default`
表示"保守 / save quota / 首次尝试"，**实现映射为省略 `--variant` flag**（不传非法值）。
归一化在 `orchestrator/workers/opencode_worker.py:_normalize_variant` 完成：

| 规格来源 variant | CLI 实际 `--variant` | 说明 |
|---|---|---|
| `default` / `None` / `""` | 省略 flag | save quota / 保守首尝试 |
| `high` | `--variant high` | 普通 GLM-5.2 coding、complex_coding、explicit_glm52 |
| `max` | `--variant max` | hard_bugfix、二次失败升级、高风险审批后 |
| `minimal` | `--variant minimal` | 极低成本子任务（保留可用） |
| 未知值 | 省略 + 记 warning | 永不传非法值给 CLI；warning 落 `result.risks` |

variant 来源优先级：`route.variant`（由 router 按 §6 填充）→ `model_spec.default_variant`
（`config/models.yaml` 的 `opencode_go_glm52.default_variant`）→ 省略。

### Orchestrator 路由 → variant 映射（规格 §6）

| 路由情形 | worker | model | variant |
|---|---|---|---|
| explicit GLM-5.2 关键词 | opencode | opencode-go/glm-5.2 | `high` |
| complex_coding | opencode | opencode-go/glm-5.2 | `high` |
| large_refactor / large_context | opencode | opencode-go/glm-5.2 | `high` |
| hard_bugfix | opencode | opencode-go/glm-5.2 | `max` |
| 项目预配 opencode worker | opencode | opencode_go_glm52 | `high` |
| save_quota / 默认首尝试 | opencode | opencode-go/glm-5.2 | 省略 flag |
| 重试升级（opencode_on_failure） | opencode | opencode_go_glm52 | `high` → `max` |
| 非 opencode 路线 | claude_code | deepseek / mimo | `None`（不传） |

`Route.variant` 透传链：`router.plan_route` 填充 → `route.json` 落盘 →
`scheduler` 持久化 `DB.route_variant` → `opencode_worker._normalize_variant` 转 CLI flag。

## 日志

- stdout → `runs/{task_id}/worker/worker.stdout.jsonl`
- stderr → `runs/{task_id}/worker/stderr.log`
- patch → `runs/{task_id}/worker/worker.patch`

## 文件所有权验证（vNext）

OpenCodeWorker 接受并验证文件所有权约束：

| 字段 | 类型 | 说明 |
|------|------|------|
| `owned_paths` | glob[] | Worker 可以修改的路径（如 `src/**`） |
| `readonly_paths` | glob[] | Worker 只能读取的路径 |
| `forbidden_paths` | glob[] | Worker 永远不能访问的路径 |

所有权验证在 worker 执行后自动进行：
- 修改 forbidden_paths 内文件 → 记录到 `result.risks`
- 修改 owned_paths 外的文件 → 记录到 `result.risks`
- 验证通过 → 所有权违规列表为空

### 热点文件默认锁（由 World Core 管理）

以下文件如果同时被多个 worker 修改，DAG 调度器会降级为串行执行：

```text
package.json  pyproject.toml  build.gradle  pom.xml
Cargo.toml    CMakeLists.txt  Dockerfile    docker-compose.yml
.env.example  数据库 migration  router config  auth config
```

## WorkerResult 输出格式（vNext）

```json
{
  "status": "success | failed | partial",
  "summary": "Worker 执行摘要",
  "changed_files": ["src/foo.py"],
  "test_suggestions": ["pytest tests/test_foo.py"],
  "risks": [],
  "needs_orchestrator_action": false,
  "stdout_path": "runs/t_001/worker/worker.stdout.jsonl",
  "stderr_path": "runs/t_001/worker/stderr.log",
  "patch_file": "runs/t_001/worker/worker.patch",
  "tests_run": [],
  "rollback_notes": "Reverse patch worker.patch"
}
```

### 新增字段说明

| 字段 | 说明 |
|------|------|
| `patch_file` | 从 worktree 导出的 `git diff --binary` patch 路径 |
| `tests_run` | 由 TestWorker 填充的测试执行记录 |
| `rollback_notes` | 回滚操作说明（如 "Reverse patch worker.patch"） |

## 与 ClaudeCodeWorker 的分工

| | ClaudeCodeWorker | World OpenCode Worker |
|---|---|---|
| **默认** | ✅ 是 | ❌ 否 |
| **后端** | DeepSeek / MiMo | opencode-go/glm-5.2 |
| **触发** | 文档、简单bug、测试、常规coding | GLM-5.2明确请求、complex_coding、失败升级 |
| **GLM** | ❌ 禁止 | ✅ 唯一 |

## 常见错误排查

1. **`opencode: command not found`** — 安装 OpenCode CLI 或设置 `AI_OPENCODE_CMD` 环境变量
2. **`--dangerously-skip-permissions` in command** — 被 `risk_policy.py` 阻断，不可绕过
3. **Worker returns "partial"** — 检查 opencode-go/glm-5.2 模型可用性

## 职责边界（规格 §7）

World OpenCode Worker **只负责**：在 git worktree 内执行被路由过来的 GLM-5.2 编码任务，
返回结构化 WorkerResult（status / summary / changed_files / patch_file / risks / rollback_notes）。

Worker 执行的自动化后处理：
- 通过 `git diff --name-only` 检测变更文件
- 通过 `git diff --binary` 导出 patch 到 `worker/worker.patch`
- 验证变更文件是否在 owned_paths 范围内、是否触碰 forbidden_paths

World OpenCode Worker **不负责**以下事项（详见规格 §7，由其它组件负责）：

| 不做的事 | 由谁负责 |
|---|---|
| 用户交互 | Codex / GPT-5.5（唯一用户入口） |
| 审批决策 | MCP Orchestrator + Dynamic Approval Graph |
| 风险分级 | Dynamic Approval Graph (`approval_graph.py`) |
| 模型路由 | MCP Orchestrator (`router.plan_route`) |
| 任务拆分 | Codex / GPT-5.5 + Orchestrator |
| 创建 PR | PR Gate（`orchestrator.pr.create_pr_or_patch`） |
| merge | 永远人工（V1 禁止 auto_merge） |
| push | Orchestrator 的 Publisher，受 `allow_remote_push` 控制 |
| policy learning | `PolicyUpdateEngine` + `ApprovalMemory` |
| final review | Codex / GPT-5.5（`orchestrator.reviewer.run_codex_review`） |
| 测试 / build / lint | Verifier（`orchestrator.verifier.verify`） |
| git diff 收集 | OpenCodeWorker 自行导出 `worker.patch`；Orchestrator verify 阶段统一生成 `verify/diff.patch` |
| AGENTS.md 模板管理 | `config/AGENTS.md.template` + 注入由 `agents_md.inject_agents_md` 负责 |

World OpenCode Worker 硬边界（永不越界）：

- 不创建 commit、不 push、不 merge、不创建 PR
- 不执行生产部署命令、不在 worktree 外执行命令
- 不绕过权限控制、不使用 `--dangerously-skip-permissions`
- 不修改 `forbidden_paths`（`.env` / `secrets/**` / `infra/prod/**` 等 18 条硬规则）
- 不修改 `owned_paths` 之外的文件（文件所有权验证）
- 不扩大任务范围超出 `task.json`

## 实现参考

核心文件：
- `orchestrator/workers/opencode_worker.py` — Worker 入口、variant 归一化、patch 导出、所有权验证
- `orchestrator/workers/base.py` — WorkerResult 基类（含 vNext 字段）
- `prompts/opencode_worker_prompt.md` — Worker 提示词（World System 上下文）
- `config/AGENTS.md.template` — AGENTS.md 注入模板

关键函数：
- `_normalize_variant()` — variant 值归一化为 CLI 可接受形式
- `assert_valid_opencode_args()` — 禁止 `--variant default` 等非法值
- `_detect_changed_files()` — `git diff --name-only` 检测变更文件
- `_export_patch()` — `git diff --binary` 导出 patch
- `_validate_file_ownership()` — 检查变更文件是否在 owned_paths 内 / 触碰 forbidden_paths
