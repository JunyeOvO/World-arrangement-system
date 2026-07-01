# World 底层代码立体扫描改进量表与门禁方案

日期：2026-07-01  
项目：`world_system`  
方式：通过 World 系统切分为 4 个只读扫描任务，由真实 worker 执行，不修改仓库文件。

## 1. 扫描证据

| 分片 | task_id | 范围 | 状态 |
| --- | --- | --- | --- |
| execution_pipeline | `t_20260701_113946_00e410` | scheduler、执行服务、attempt runner、completion pipeline、stale reaper | `COMPLETED_WITH_ARTIFACTS` |
| routing_policy_workers | `t_20260701_114115_46cbea` | router、routing、approval、risk、workers、prompt、read-only、failure classifier | `COMPLETED_WITH_ARTIFACTS` |
| console_db_metrics | `t_20260701_114336_e26b1a` | console、DB、artifact、metrics、token ledger、outcomes | `COMPLETED_WITH_ARTIFACTS` |
| cli_mcp_runtime | `t_20260701_114702_69611b` | CLI、MCP、project registry、runtime store、task submission | `COMPLETED_WITH_ARTIFACTS` |

所有分片均按只读任务执行，worker 报告 `changed_files=[]`。本文件是扫描结果的归纳规划，不代表已完成代码修复。

## 2. 总体结论

World 系统已经具备可用的任务提交、worker 路由、只读审计、Console 展示和 token/cost 统计闭环，但底层仍存在 4 类结构性风险：

1. 执行链路存在隐藏状态突变，`task`、`attempt`、`WorkerResult` 在多个服务之间被原地修改，导致最终状态依赖调用顺序。
2. 路由、风险、审批、worker/model 选择存在策略分散，新增模型或 worker 时需要同步修改多个模块。
3. Console/DB/metrics 层存在查询、派生、展示格式混杂，状态分类和 token/cost 可信度仍需要单一事实源。
4. CLI/MCP/runtime 的调用边界不一致，MCP 暴露能力、安全、参数校验和 RuntimeStore 写入副作用需要加强。

下一阶段不应继续只加功能，而应先建立门禁，把“可用”推进到“可长期迭代、可证明真实、可防误用”。

## 3. 改进量表

每个维度按 0-5 分评估：

| 分数 | 含义 |
| --- | --- |
| 0 | 不存在明确设计，靠调用者经验维持 |
| 1 | 有局部实现，但职责混乱且缺少测试 |
| 2 | 有模块边界，但存在重复策略或隐藏副作用 |
| 3 | 有清晰 owner 和核心测试，仍缺少跨模块门禁 |
| 4 | 单一事实源、接口稳定、回归测试覆盖主要路径 |
| 5 | 具备扩展注册机制、契约测试、失败降级和观测闭环 |

| 维度 | 当前估计 | 目标 | 主要差距 |
| --- | ---: | ---: | --- |
| GRASP 职责内聚 | 2 | 4 | execution callback、ConsoleQueries、completion pipeline 承担过多职责 |
| GoF 策略封装 | 2 | 4 | retry chain、routing、risk、approval 多处重复策略 |
| 状态不可变与结果一致性 | 1 | 4 | `task`、`attempt`、`WorkerResult` 原地突变 |
| Worker/model 注册与校验 | 2 | 5 | magic string 分散，force worker/model 缺少前置校验 |
| Console 真实性 | 2 | 4 | status/outcome/token/cost 多源派生，view-model 和 DB 读取混杂 |
| Artifact 安全边界 | 3 | 4 | 部分 JSON 读取路径未统一走 whitelist |
| CLI/MCP 协议一致性 | 2 | 4 | MCP 参数面少于 CLI，部分字段任意字符串透传 |
| RuntimeStore 安全 | 2 | 4 | backend resolve 有写入副作用，JSON 写入非原子 |
| 测试与门禁 | 2 | 4 | 有单元测试基础，但缺少架构契约和安全门禁 |
| 真实应用节省 Codex 工作量 | 3 | 4 | 小样本可分流，但结果可信度依赖状态、token、artifact 门禁 |

## 4. P0-P3 改进规划

### P0：先修正真实性和安全边界

目标：避免系统给出错误状态、错误费用、错误审批结论。

- 统一 status/outcome/dashboard 分类常量，`dashboard_status.py` 与 `outcomes.py` 不再维护重复集合。
- `WorkerResult`、attempt、task preparation 改为 copy-before-mutate，禁止跨服务原地修改输入对象。
- `TaskSubmissionService` 前置校验 `force_worker`、`force_model`、`force_variant`、`task_mode`、`verification_policy`、`read_budget_profile`。
- RuntimeStore `resolve_backend()` 不允许写业务仓库；`.gitignore` 写入应移到显式 setup/repair 流程。
- Console artifact JSON 读取统一走公开 artifact whitelist。
- MCP 工具增加本机安全边界与 token 校验，至少保证只监听 `127.0.0.1` 且需要 `WORLD_MCP_TOKEN` 或等价本地授权。

### P1：抽离策略和 view-model

目标：把“改一个模型/状态/指标要碰多个文件”的风险降下来。

- 建立 worker/model registry，统一 display name、provider、capability、price profile、allowed agents。
- 合并 retry chain 策略：`routing/policy.py`、`router_route_policy.py`、`routing/decision.py` 只保留一个策略 owner。
- 将 risk/safety/approval 组成一个 `ExecutionPolicyDecision`，输出 allow/block/approval/budget/actionable_reason。
- 继续完成 Console metrics view-model 抽离：DB 层只读原始行，view-model 层负责显示名、duration、cost、token efficiency。
- 将 token/cost 输出拆成 `backend_calculated_cost_usd`、`adapter_reported_cost_usd`、`cost_trust`。

### P2：增强执行器级控制

目标：让 worker 少走弯路，减少 Codex 调度和 review 的 token 消耗。

- 对 `quick_triage`、`code_contract_audit`、`docs_review` 继续推广 seed evidence。
- 为所有 read-only 任务记录 `silent_max_turns_no_output`、seed 命中率、salvage 类型。
- 为 read budget profile 增加强制“一候选即输出草案”的执行器级控制，而不是只靠 prompt 约束。
- 对 long-running attempt 增加 wall-clock circuit breaker 和指数退避。

### P3：发布与生态化

目标：支持更多真实项目接入，而不扩大维护复杂度。

- CLI/MCP 参数面完全对齐，MCP 支持 dry-run、force worker/model、control plane。
- 增加项目注册健康检查：路径存在、默认分支、命令匹配、allow_auto_pr、安全写策略。
- 增加架构质量矩阵报告命令，输出趋势而非单次快照。
- 建立 release gate：没有通过 P0/P1 门禁不得标记为生产可用。

## 5. 门禁方案

### 5.1 本地提交前门禁

```powershell
uv run pytest
uv run pytest tests/test_console_status.py tests/test_console_metrics_usage.py tests/test_task_outcomes.py
rg -n "sk-[A-Za-z0-9_-]{16,}|API_KEY|SECRET|TOKEN|PASSWORD" -g "!*.example" -g "!uv.lock" .
```

说明：secret 扫描命令只作为基础门禁；若未来增加真实 CI，应接入专门 secret scanner。

### 5.2 架构契约门禁

- 新增或修改执行链路时，必须证明输入对象不被原地修改。
- 新增 worker/model 时，只允许通过 registry 注册，不允许在 router、worker、prompt 中散落 magic string。
- 新增 status 时，必须同时通过 status mapping、outcome derivation、dashboard count、Console badge 测试。
- 新增 artifact 展示时，必须加入 whitelist 测试，禁止任意路径 JSON 读取。
- 新增 cost/token 字段时，必须说明真实来源：adapter、backend pricing、Codex estimate 或 unavailable。

### 5.3 Console 真实性门禁

- Running/Queued/Failed/Approval/Alerts 的顶部计数只能来自 dashboard status 派生函数。
- `STALE_EXECUTING` 不应同时计入健康 Running；需要明确展示为 stale/alert。
- token 显示必须是后端汇总后的真实字段；估算字段必须显式标记 estimate。
- cost 显示必须来自后端 price table 计算；没有 price table 时显示 trust 状态，而不是伪装为真实价格。

### 5.4 Read-only Worker 门禁

- read-only 任务必须满足 `changed_files=[]`。
- 允许 partial-result salvage，但必须标记 salvage 类型和 evidence completeness。
- mock/degraded 结果不得显示为 approved/can create PR。
- 对 code scan 任务必须输出：范围、已读文件数、发现、严重度、建议测试、下一步切片。

### 5.5 Runtime/MCP 门禁

- RuntimeStore 的检查方法不得写业务仓库。
- 删除/cleanup 必须校验路径在 World runtime 根目录下，且默认不删除整个 project store。
- MCP submit/approve/cancel/read-result 必须具备本机访问控制。
- CLI 和 MCP 对 task protocol 字段必须共享同一套校验函数。

## 6. 优先切片

### Slice A：执行链路不可变修复

范围：
- `task_preparation.py`
- `worker_attempt_executor.py`
- `task_attempt_runner.py`
- `task_completion_pipeline.py`
- `post_attempt_policy.py`

验收：
- 新增 copy-before-mutate 测试。
- read-only salvage 不修改原始 `WorkerResult`。
- retry chain attempt dict 不被 executor 原地污染。

### Slice B：状态与 Console 单一事实源

范围：
- `dashboard_status.py`
- `outcomes.py`
- `console/queries.py`
- Console serializers/view-model

验收：
- 所有 raw status 有唯一 big status 映射。
- outcome、dashboard、Console badge 使用同一常量。
- stale 状态和 active 状态不互相冲突。

### Slice C：Worker/model registry

范围：
- routing policy
- worker implementations
- display names
- pricing/token profile

验收：
- force worker/model 前置校验。
- display name、agent name、model price 使用 registry。
- 新增模型只改 registry 和测试 fixture。

### Slice D：Runtime/MCP 协议硬化

范围：
- `mcp_server.py`
- `cli.py`
- `task_submission.py`
- `runtime_store.py`
- `world_runtime_service.py`

验收：
- MCP/CLI 参数面一致。
- invalid task protocol 立即失败并给出明确原因。
- RuntimeStore resolve 不写 `.gitignore`。
- MCP 本机安全边界有测试覆盖。

## 7. 下一轮 World 分派建议

建议下一轮不要再做全量扫描，直接分 4 个实现任务：

1. `Slice A`：执行链路不可变修复，风险最高，优先级 P0。
2. `Slice B`：status/outcome/dashboard 单一事实源，直接影响 Console 可信度。
3. `Slice C`：worker/model registry，降低后续模型扩展成本。
4. `Slice D`：MCP/runtime 安全和协议一致性，决定真实项目接入边界。

每个实现任务都应要求：

- 保护现有未提交变更。
- 不读取或输出 secrets。
- 不改 `.env`、缓存、运行日志、worker 产物。
- 先写或更新针对性测试。
- 返回变更文件、测试结果、风险、下一步。
- 不自动 merge，不自动 PR。

## 8. 验收标准

本轮规划文档自身的验收标准：

- 已覆盖四个底层扫描分片。
- 每个分片有可追溯 task_id。
- 输出包含量表、P0-P3 规划、门禁、优先切片。
- 不修改运行代码。
- 不包含 secret 或 profile 值。

下一阶段代码修复的验收标准：

- P0 切片完成后，`uv run pytest` 通过。
- Console 顶部状态、详情状态、Recent Tasks 状态来自同一映射。
- read-only 任务失败、partial、salvage、mock/degraded 均能被真实区分。
- token/cost 页面能说明真实值、估算值、不可用值的边界。
- World 自身被注册为可持续迭代项目，而不是只能人工扫描。
