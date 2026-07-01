# World 底层代码续扫记录：扫描至无新增 P0-P2

日期：2026-07-01  
项目：`world_system`  
目标：在已完成第一轮底层扫描的基础上继续切分扫描，直到后续扫描不再产出新的 P0-P2 问题。

## 1. 停止条件

本轮采用可执行的停止条件，而不是声称全项目形式化证明：

- 每一轮把上一轮新增 P0-P2 纳入基线。
- 后续 worker 只允许报告“基线外新增 P0-P2”。
- 若完整交叉确认扫描返回 `NO_NEW_P0_P2`，且 partial 扫描没有给出新的可采纳证据，则停止。

最终停止依据：

- `t_20260701_120943_4abd49` 完整完成，返回 `NO_NEW_P0_P2`。
- `t_20260701_120943_58e7dc` 为 partial artifact，但没有给出新的基线外 P0-P2 证据。

## 2. 轮次与任务

| 轮次 | task_id | 主题 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| Round 2 | `t_20260701_115704_189519` | tests/CI/gates | `COMPLETED_WITH_ARTIFACTS` | 新增 P2 |
| Round 2 | `t_20260701_115704_ef6fcc` | console-web/API contract | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | partial，新线索需复核 |
| Round 2 | `t_20260701_115704_99dbef` | schemas/config/prompts | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | 新增 P1/P2 |
| Round 2 | `t_20260701_115704_fa2f13` | process/WSL/concurrency | `COMPLETED_WITH_ARTIFACTS` | 新增 P0/P1/P2 |
| Round 3 | `t_20260701_115933_a102eb` | Console/API/server security | `COMPLETED_WITH_ARTIFACTS` | 新增 P1/P2 |
| Round 3 | `t_20260701_115933_b00908` | DB/transaction/ledger | `COMPLETED_WITH_ARTIFACTS` | 新增 P0/P1/P2 |
| Round 3 | `t_20260701_115933_10cd09` | dependency/deploy/profile | `COMPLETED_WITH_ARTIFACTS` | 新增 P1/P2 |
| Round 3 | `t_20260701_115933_640cc7` | project/skill/runtime contract | `COMPLETED_WITH_ARTIFACTS` | 新增 P1/P2 |
| Round 4 | `t_20260701_120230_fee12c` | remaining orchestrator modules | `COMPLETED_WITH_ARTIFACTS` | 新增 P1/P2 |
| Round 4 | `t_20260701_120230_cd7d37` | cross-module contract | `COMPLETED_WITH_ARTIFACTS` | 新增 P1/P2 |
| Round 4 | `t_20260701_120230_43662a` | delete/path/cleanup | `FAILED_FINAL` | 未采纳，后续缩小重跑 |
| Round 5 | `t_20260701_120628_5480d8` | global stop-check | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | partial，无最终新增结论 |
| Round 5 | `t_20260701_120628_87584e` | delete/path/cleanup rerun | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | 新增 P1/P2 |
| Round 5 | `t_20260701_120628_d03b17` | lifecycle/actions | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | 新增 P2 |
| Round 6 | `t_20260701_120943_58e7dc` | final stop-check | `COMPLETED_WITH_PARTIAL_ARTIFACTS` | 未提出新增可采纳证据 |
| Round 6 | `t_20260701_120943_4abd49` | independent cross-confirmation | `COMPLETED_WITH_ARTIFACTS` | `NO_NEW_P0_P2` |

## 3. 新增问题归类

### P0

| 问题 | 证据 | 影响 | 建议门禁 |
| --- | --- | --- | --- |
| WSL 边界 env 清洗被绕过 | `command_utils.py`、`workers/claude_code_worker.py` | WSL subprocess 继承完整 `os.environ`，可能把 provider key 和 proxy 暴露给 worker shell | WSL 命令必须传入清洗后的 env；增加 env 继承回归测试 |
| `TaskDB.connect()` 异常时连接泄漏 | `orchestrator/db.py` | 非 `OperationalError` 从 `with` 块抛出时连接无法关闭，长时间运行会耗尽 DB 连接/FD | `try/finally close`，并增加 caller exception 测试 |
| `learned_patterns` 缺少唯一约束 | `orchestrator/db.py` | 并发 upsert 可产生重复学习记录，策略学习失真 | 增加 `(project_id, task_type, path_pattern)` 唯一索引或 `ON CONFLICT` |

### P1

| 问题 | 证据 | 影响 | 建议门禁 |
| --- | --- | --- | --- |
| 控制文件缺少跨进程锁 | `process_control.py`、`stale_worker_reaper.py` | scheduler/reaper/cancel 并发读写可能损坏 process/heartbeat 状态 | 文件锁或单写者 DB 事务 |
| PID 复用导致 stale worker 误判存活 | `stale_worker_reaper.py` | 已死 worker 的 PID 被复用时，任务可能永久卡在 executing | process token/start time 双重校验 |
| stream JSONL 退出不完整 | `process_control.py`、worker stream parser | SIGKILL 后最后一行可能截断，恢复数据不可信 | clean-exit sentinel，读取时跳过不完整最后行 |
| worker prompt contract 字段不一致 | `prompts/worker_prompt.md`、`schemas/result.schema.json`、`worker_prompt.py` | worker 按模板输出 `needs_orchestrator_action` 时不符合真实 schema | 统一字段名并对 prompt/schema 做契约测试 |
| Console 零认证 | `orchestrator/console/app.py` | 非 localhost 或误配置 host 时可读写全部 Console API | shared secret 或本地 token gate |
| Console POST 无 CSRF/Origin 防护 | `orchestrator/console/app.py`、`console-web/src/api/client.ts` | 绑定到非 localhost 时可被跨站触发状态变更 | Origin/Referer 校验或 CSRF token |
| token ledger 多查询非原子读取 | `orchestrator/token_ledger.py` | token/cost ledger 内部可能来自不同时间点 | 单事务快照读取 |
| attempt/codex/baseline 写入链无原子性 | `attempt_recording.py`、`codex_usage_recording.py`、`task_operations.py` | DB 与 artifact/ledger 可能不一致 | DB 事务 + artifact/ledger best-effort 失败告警 |
| MCP 安装命令缺 mcp extra | `pyproject.toml`、`README.md`、`scripts/install.sh` | 按 README 安装后可能无法运行 MCP server | 统一为 `uv sync --all-extras` 或显式 `--extra mcp` |
| MCP submit 参数面缺 force/dry-run | `mcp_server.py`、`cli.py`、`task_submission_service.py` | LLM/MCP 主入口无法强制 worker/model 或 dry-run | MCP tool 与 service 参数契约测试 |
| project memory 从 repo 而非 worktree 构建 | `project_memory.py`、`task_submission.py` | worker 隔离 worktree 与 memory 不一致 | memory 支持 worktree/ref 来源 |
| `_command_matches` 前缀匹配可被链式 shell 绕过 | permissions 相关模块 | 允许命令尾部拼接危险操作 | 命令解析为 argv，拒绝 shell 元字符 |
| hard approval approve 后不恢复执行 | `task_execution_gate.py`、`task_execution_service.py`、`scheduler.py` | 用户批准后任务仍停在等待审批状态 | approve 后显式 resume execution 并重记 outcome |
| RuntimeStore cleanup `run_id` 路径穿越 | `runtime_store.py` | 若 `run_id` 可控，`..` 可绕过删除边界 | validate run_id segment，resolve 后 relative_to runtime root |

### P2

主要 P2 类别：

- CI 门禁：`--maxfail=1`、未运行 mypy、未检查 ruff format、无 coverage threshold。
- Console/API：SSE 连接无上限、POST 子串匹配、静态资源 cache-control、内部 artifact JSON 缺二次路径校验。
- DB/metrics：`_ensure_column` TOCTOU、未启用 WAL、`codex_share_pct` 混合真实和估算 token。
- 部署/profile：GLM profile 与 README 版本漂移、硬编码 `/home/junye`、MCP entrypoint 不一致、前端 build tool 在 dependencies、MiMo profile 缺 subagent model。
- Runtime/contract：CLI 缺 `submit-current-project-task`、World plan route 与 scheduler route 独立、`**protocol` 有覆盖关键字段风险、RuntimeStore 调用 `type: ignore`。
- 质量矩阵：unknown model 静默按 `$0` 计费，`quality_state` 把 `None` 验证当作通过，baseline artifact 持久化原始 repo_path。
- 生命周期：approve 返回成功但不表示任务恢复，MCP/CLI reject/cancel 缺状态机 guard，worktree cleanup 对 task_id 缺路径段校验。

## 4. 当前修复优先级

优先级应按“会导致 secrets 暴露、数据损坏、任务永久卡死、成本真实性错误”的顺序推进。

1. P0 安全与数据一致性：
   - WSL env 清洗。
   - DB connect finally close。
   - learned_patterns 唯一约束和迁移。
2. P1 状态与执行恢复：
   - hard approval approve 后恢复执行。
   - reject/cancel 状态机 guard。
   - PID token、文件锁、stream sentinel。
3. P1/P2 真实度：
   - unknown model 不能静默 `$0`。
   - token/cost 拆分真实、估算、不可用。
   - Console auth/CSRF 先做最小本地 token。
4. P2 工程门禁：
   - CI mypy/format/coverage。
   - schema/prompt/profile/docs consistency tests。
   - MCP/CLI 参数面一致性 tests。

## 5. 下一步执行建议

不要继续扩大扫描，当前高优先级缺陷已经足够多。下一步应该进入修复：

1. `Slice P0-A`: WSL env + DB connect + learned_patterns unique。
2. `Slice P1-B`: hard approval resume + cancel/reject state guard。
3. `Slice P1-C`: Runtime cleanup/worktree path validation + command permission parser。
4. `Slice P1-D`: Console auth/CSRF + SSE connection cap。
5. `Slice P2-E`: CI/schema/profile/docs 门禁。

每个 slice 的验收：

- 先补针对性测试。
- 不读取或输出 secrets。
- 不改 `.env`、缓存、运行日志、worker 产物。
- `uv run pytest` 或至少相关测试通过。
- Console/API 行为变化需有前后状态说明。

## 6. 局限

- World worker 任务有 read budget；部分扫描是 partial artifact。
- 第六轮完整确认说明在其覆盖范围内没有新增 P0-P2，但不等同于形式化证明。
- 当前仓库存在未提交 Console metrics WIP；本轮只读扫描没有修改这些文件。
