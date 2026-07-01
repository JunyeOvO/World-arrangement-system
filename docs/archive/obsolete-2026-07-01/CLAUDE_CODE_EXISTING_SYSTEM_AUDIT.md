# Claude Code Existing System Audit

> 生成时间: 2026-06-27  
> 审计人: Claude Code (Windows 侧)  
> 仓库: `ai-orchestrator-v1` @ `C:\Users\fujunye\Documents\Codex\2026-06-24\li\outputs\ai-orchestrator-v1`

> Status: historical snapshot. This audit records the pre-World-vNext state and is kept for traceability. Current routing rules are defined in `docs/MODEL_ROUTING.md`, `docs/WORLD_SYSTEM_OVERVIEW.md`, and `orchestrator/router.py`.

---

## 1. 当前已实现模块列表

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| Package init | `orchestrator/__init__.py` | ✅ 完成 | `__version__ = "0.1.0"` |
| MCP Server | `orchestrator/mcp_server.py` | ⚠️ 部分 | 9个核心工具完整；**缺失9个审批工具** |
| Router | `orchestrator/router.py` | ⚠️ 部分 | 7分支路由逻辑存在；**从未选择OpenCodeWorker** |
| State Machine | `orchestrator/state_machine.py` | ⚠️ 部分 | 18状态/28转换；**命名不符合最新要求，缺失审批状态流** |
| Risk Policy | `orchestrator/risk_policy.py` | ✅ 完成 | 静态规则检查，含命令扫描和文件检查 |
| Scheduler | `orchestrator/scheduler.py` | ⚠️ 部分 | 完整生命周期引擎；**缺失policy_learning和create_pr步骤** |
| Project Registry | `orchestrator/project_registry.py` | ✅ 完成 | 5层检测策略 |
| Database | `orchestrator/db.py` | ⚠️ 部分 | 3表（tasks, task_events, task_attempts）；**缺失4个审批表** |
| Config | `orchestrator/config.py` | ✅ 完成 | 路径管理 + YAML加载 |
| CLI | `orchestrator/cli.py` | ⚠️ 部分 | 6个子命令；**缺失cancel和rollback CLI** |
| Command Utils | `orchestrator/command_utils.py` | ✅ 完成 | 跨平台命令构建 |
| Constants | `orchestrator/constants.py` | ⚠️ 有bug | 禁用模式中有**拼写错误** |
| Env Profiles | `orchestrator/env_profiles.py` | ✅ 完成 | 模型→环境变量映射 |
| Artifacts | `orchestrator/artifacts.py` | ✅ 完成 | 安全文件存储，原子写入 |
| Worktree | `orchestrator/worktree.py` | ✅ 完成 | Git worktree隔离 |
| Verifier | `orchestrator/verifier.py` | ✅ 完成 | 测试+构建验证 |
| Reviewer | `orchestrator/reviewer.py` | ✅ 完成 | Codex审查 + 本地回退 |
| PR | `orchestrator/pr.py` | ⚠️ **孤儿** | 功能完整但**从未被调度器调用** |
| ClaudeCodeWorker | `orchestrator/workers/claude_code_worker.py` | ✅ 完成 | 默认Worker |
| OpenCodeWorker | `orchestrator/workers/opencode_worker.py` | ⚠️ 部分 | **缺失`--title`参数** |
| CodexReviewWorker | `orchestrator/workers/codex_review_worker.py` | ✅ 完成 | Stub委托给reviewer.py |
| MimoWorker | `orchestrator/workers/mimo_worker.py` | 🔧 脚手架 | 仅占位，需API集成 |

---

## 2. 当前 MCP Tools 列表

### 已实现 (9个)
1. `list_projects`
2. `detect_project`
3. `submit_task`
4. `submit_current_project_task`
5. `get_task_status`
6. `read_task_result`
7. `cancel_task`
8. `rollback_task`
9. `open_task_artifacts`

### 缺失 — Dynamic Approval Graph 工具 (9个)
1. `get_approval_decision` — **未实现**
2. `approve_task` — **未实现**
3. `reject_task` — **未实现**
4. `list_learned_rules` — **未实现**
5. `revoke_learned_rule` — **未实现**
6. `explain_approval` — **未实现**
7. `list_policy_suggestions` — **未实现**
8. `approve_policy_suggestion` — **未实现**
9. `reject_policy_suggestion` — **未实现**

---

## 3. 当前 Worker 列表

| Worker | 类名 | 触发条件（当前） |
|--------|------|-----------------|
| ClaudeCodeWorker | `ClaudeCodeWorker` | 默认 fallback；docs/readme/simple tasks |
| OpenCodeWorker | `OpenCodeWorker` | 从未被 router 选择（缺失GLM-5.2检测） |
| CodexReviewWorker | `CodexReviewWorker` | Stub — 实际审查由 reviewer.py 完成 |
| MimoWorker | `MimoWorker` | 含 multimodal 关键词的任务 |

---

## 4. 当前 Router 策略

`plan_route()` 有 7 个分支：

| 优先级 | 条件 | 模型 | Worker |
|--------|------|------|--------|
| 1 | multimodal关键词 | `mimo_multimodal` | `mimo` |
| 2 | high risk + auth/refactor/architecture/migration/prod关键字 | `glm_advanced` | `claude_code` |
| 3 | docs/readme/tests 关键字 | `deepseek_pro` | `claude_code` |
| 4 | 项目stack匹配Android/Kotlin/FastAPI/React/Vue | 项目default_model | 项目default_worker |
| 5 | 默认 | `deepseek_pro` | `claude_code` |

**关键缺失**: OpenCodeWorker 从未被 `plan_route()` 选中。`"opencode"` 这个字符串在 `router.py` 中不存在。GLM-5.2 检测逻辑缺失。

---

## 5. 当前测试覆盖情况

### 测试统计
- **15 个测试全部通过** (0.32s)
- 所有测试均为 dry-run 路径，不需要真实 CLI 或 API key

### 测试文件覆盖

| 文件 | 测试数 | 覆盖场景 |
|------|--------|---------|
| `test_command_utils.py` | 2 | 普通命令构建、WSL env注入 |
| `test_env_profiles.py` | 2 | .env解析、runtime home profile |
| `test_project_registry.py` | 1 | .ai-project.yaml 检测 |
| `test_risk_policy.py` | 3 | auto_merge禁止、禁止路径、禁止命令 |
| `test_router.py` | 3 | docs路由、high risk路由、multimodal路由 |
| `test_schemas.py` | 1 | JSON Schema 有效性 |
| `test_state_machine.py` | 2 | 有效转换、无效转换 |
| `test_worktree.py` | 1 | dry-run worktree |

### 要求中指定的11个新测试 — 全部缺失
1. `test_router_default_claude_code` — ❌
2. `test_router_explicit_glm52_uses_opencode` — ❌
3. `test_router_complex_coding_uses_opencode` — ❌
4. `test_router_claude_failure_escalates_to_opencode` — ❌
5. `test_opencode_worker_command` — ❌
6. `test_opencode_worker_forbids_dangerous_skip_permissions` — ❌
7. `test_dynamic_approval_forbidden_path_blocked` — ❌
8. `test_dynamic_approval_repeated_low_risk_can_auto` — ❌
9. `test_dynamic_approval_high_risk_never_auto` — ❌
10. `test_dynamic_approval_rollback_demotes_trust` — ❌
11. `test_detect_project_from_global_projects_yaml` — ❌

---

## 6. 当前缺失项

### 严重 (阻塞发布)
| # | 缺失项 | 涉及文件 |
|---|--------|---------|
| 1 | **Dynamic Approval Graph 全部缺失**: 5个模块、9个MCP工具、4个DB表 | 新建5个文件 + 修改3个文件 |
| 2 | **Router 从不选择 OpenCodeWorker** | `router.py` |
| 3 | **OpenCodeWorker 缺少 `--title` 参数** | `workers/opencode_worker.py` |
| 4 | **PR模块是孤儿代码** — 从不被调度器调用 | `scheduler.py`, `pr.py` |
| 5 | **Scheduler 缺少 policy_learning 步骤** | `scheduler.py` |

### 重要
| # | 缺失项 | 涉及文件 |
|---|--------|---------|
| 6 | 状态机命名不符合最新规范 (25个要求状态 vs 18个现有状态) | `state_machine.py` |
| 7 | `constants.py` 中 `--dangerously-skip-permissions` 拼写错误 | `constants.py` |
| 8 | CLI 缺少 `cancel-task` 和 `rollback-task` 子命令 | `cli.py` |
| 9 | 无 `scripts/doctor.ps1` (Windows) | 新建 |
| 10 | 无 `scripts/opencode-smoke-test.sh` | 新建 |

### 文档
| # | 缺失文档 |
|---|---------|
| 11 | `docs/OPENCODE_WORKER.md` — 缺失 |
| 12 | `docs/DYNAMIC_APPROVAL_GRAPH.md` — 缺失 |
| 13 | `docs/GLOBAL_PROJECTS.md` — 缺失 |
| 14 | `docs/WINDOWS_WSL_DEPLOYMENT.md` — 缺失 |
| 15 | 需更新: `README.md`, `docs/ARCHITECTURE.md`, `docs/V1_SOP.md`, `docs/SECURITY.md`, `docs/MODEL_ROUTING.md` |

---

## 7. 本次增量修改计划

### 阶段 1: 修复关键缺陷 (先让现有系统正确)
1. **OpenCodeWorker**: 添加 `--title TASK_ID` 参数
2. **Router**: 添加 GLM-5.2 检测 → 路由到 OpenCodeWorker
3. **Scheduler**: 连接 PR 模块到生命周期
4. **Constants**: 修复 `--dangerously-skip-permissions` 拼写

### 阶段 2: Dynamic Approval Graph (核心新功能)
5. 新建 `orchestrator/approval_graph.py`
6. 新建 `orchestrator/approval_memory.py`
7. 新建 `orchestrator/approval_scorer.py`
8. 新建 `orchestrator/policy_update_engine.py`
9. 新建 `orchestrator/approval_explainer.py`
10. 扩展 `db.py` — 添加4个审批表
11. 扩展 `mcp_server.py` — 注册9个审批MCP工具
12. 扩展 `state_machine.py` — 添加审批相关状态

### 阶段 3: 状态机升级
13. 重命名状态以匹配新规范 (保留旧状态作为别名)
14. 添加 POLICY_LEARNING 状态和转换

### 阶段 4: 测试和文档
15. 添加11个新测试
16. 创建缺失的4个文档
17. 更新现有5个文档
18. 新增 `scripts/doctor.ps1` 和 `scripts/opencode-smoke-test.sh`

---

## 8. 沿用的 Codex 实现

以下模块 **不需要修改**，将直接沿用：

- `orchestrator/artifacts.py` — 完整的 artifact 存储层
- `orchestrator/command_utils.py` — 跨平台命令构建
- `orchestrator/config.py` — 配置加载
- `orchestrator/env_profiles.py` — 环境变量管理
- `orchestrator/project_registry.py` — 项目检测（5层策略）
- `orchestrator/workers/base.py` — Worker 抽象接口
- `orchestrator/workers/claude_code_worker.py` — 默认 Worker
- `orchestrator/workers/mimo_worker.py` — 保留脚手架（无需修改）
- `orchestrator/worktree.py` — Git worktree 隔离
- `orchestrator/verifier.py` — 测试/构建验证
- `orchestrator/reviewer.py` — Codex 审查
- `orchestrator/__init__.py` — 包初始化
- 所有 `profiles/` — 环境配置模板
- 所有 `prompts/` — Worker/Reviewer 提示
- 所有 `schemas/` — JSON Schema 契约
- 所有现有 tests — 保留并扩展（不删除旧测试）
- `config/` 模板 — 配置示例
- `scripts/install.sh`, `scripts/doctor.sh`, `scripts/create-pr.sh`, `scripts/run-mcp.sh`, `scripts/run-once.sh`
