# PLAN.md — OpenCode 全自动系统设置落地计划

> 目标：把《OpenCode 全自动系统设置提示词》7 节规格接入已有的 `ai-orchestrator-v1`，**不推倒重写、不删文件、不改业务逻辑，只增量补齐 OpenCodeWorker / GLM-5.2 链路**。

---

## 0. 路径与基线约定（先对齐，避免歧义）

| 规格写法 | 实际位置 | 当前状态 |
|---|---|---|
| `~/ai-orchestrator-v1` | `/mnt/c/Users/fujunye/Documents/Codex/2026-06-24/li/outputs/ai-orchestrator-v1`（WSL 挂载的 Windows Codex 产物） | **存在且完整**，是 Codex 已实现的真身 |
| `~/.config/opencode/opencode.json` | `~/.config/opencode/opencode.jsonc` | 存在但**空**，仅一行 `$schema` |
| `~/repos/<project>/AGENTS.md` | 业务仓占位符 | **不创建**；本次只在 orchestrator 仓内沉淀模板与注入机制 |
| `AI_ORCHESTRATOR_HOME` | `~/.ai-orchestrator/`（运行时） | 由 `scripts/install.sh` 创建，与本仓分离 |

**遗留路径问题**（非本次任务但需登记）：`.env.example`、`config/codex-mcp.config.example.toml`、`config/projects.yaml.example` 硬编码 `/home/junye/...`，与本机 `fujunye` 不一致。本次不改（属用户配置层），仅在 PLAN 风险点登记，并在新/改文件中改用 `$HOME` 或相对引用。

**建议（待你拍板）**：是否在 Linux home 建 `~/ai-orchestrator-v1 -> /mnt/c/.../ai-orchestrator-v1` 软链，让规格里的 `~/ai-orchestrator-v1` 字面可用。这是唯一需要写 `~/` 的动作，不在本计划默认执行，等你确认。

---

## 1. 当前已实现模块盘点（Codex 已写，本计划沿用）

| 模块 | 文件 | 与规格的对应 | 健康度 |
|---|---|---|---|
| 全局 opencode CLI | `~/.local/bin/opencode` v1.17.11 支持 `-m/--variant/--format json/--dir/--title` | 规格 §4 命令模板载体 | ✅ 已具备 |
| Worker 基类 | `orchestrator/workers/base.py` | Worker/WorkerResult 契约 | ✅ 沿用 |
| OpenCodeWorker | `orchestrator/workers/opencode_worker.py:46-61` 命令构造 | 规格 §4 命令模板 | ⚠️ 结构对，但 **variant 不生效**（见 §3-G2） |
| ClaudeCodeWorker | `orchestrator/workers/claude_code_worker.py:13-32` 拒 GLM | 规格 §5 GLM 不走 Claude | ✅ 已落实（含测试 `tests/test_workers.py:16`） |
| 路由器 | `orchestrator/router.py:44-99` | 规格 §5 路由规则 | ✅ 主体匹配，**仅缺 variant 透传** |
| 升级链 | `orchestrator/scheduler.py:458-503` `_build_retry_chain` | 规格 §6 retry_after_* | ✅ 已有 opencode_on_failure → high → max |
| 禁止动作 | `orchestrator/constants.py:17-28` 含 `--dangerously-skip-permissions` | 规格 §4 禁止项 | ✅ 已落实（`risk_policy.scan_command` 拦截） |
| 禁止路径 | `orchestrator/constants.py:30-44` | 规格 §2 Hard Rules 1-8 | ✅ 已落实 |
| 动态审批图 | `orchestrator/approval_graph.py` | 规格 §7 "Dynamic Approval Graph 负责 approval" | ✅ 沿用 |
| 状态机 | `orchestrator/state_machine.py` | 规格 §7 "MCP Orchestrator 负责 state machine" | ✅ 沿用 |
| Verifier / Reviewer / PR Gate | `orchestrator/verifier.py` / `reviewer.py` / `pr.py` | 规格 §7 Verifier / final review / PR Gate 分工 | ✅ 沿用 |
| MCP 单入口 | `orchestrator/mcp_server.py` + `config/codex-mcp.config.example.toml` | 规格 §7 "Codex 是唯一用户入口" | ✅ 沿用 |
| 模型/策略/项目配置 | `config/models.yaml.example` / `policies.yaml.example` / `projects.yaml.example` | 规格 §5/§6 数据源 | ✅ 沿用，仅补 variant 字段语义 |
| env profile 隔离 | `orchestrator/env_profiles.py` + `profiles/*.env.example` | README §"DeepSeek and MiMo with Claude Code" | ✅ 沿用（GLM 走 opencode 原生，无需 env profile） |
| Smoke 脚本 | `scripts/opencode-smoke-test.sh` | 规格 §4 禁止项校验 | ⚠️ 仅 grep help，无真实 GLM 调用 |
| Worker 通用 Prompt | `prompts/worker_prompt.md` | — | ❌ 通用版，非规格 §3 的 OpenCodeWorker 专用 Prompt |
| 现有测试 | `tests/test_workers.py` / `test_router.py` 等 13 个 | — | ✅ 13 个测试，作为回归基线 |

---

## 2. 缺失模块清单（对照规格 7 节）

| 编号 | 缺失项 | 规格出处 | 影响 |
|---|---|---|---|
| G1 | `~/.config/opencode/opencode.jsonc` 未写 `model: opencode-go/glm-5.2` | §1 | 非该 orchestrator 调起的 opencode 调用会用默认模型，不一致 |
| G2 | `Route` dataclass 无 `variant` 字段；`router.py` 局部算出 variant 仅写进 `reason` 文案，**不进 route dict** | §4 / §6 | `opencode_worker.py:58` 永远拿不到 variant，primary GLM 调用恒不传 `--variant` |
| G3 | `models.yaml` key `opencode_go_glm52` 与 router 用值 `opencode-go/glm-5.2` **对不上** → `model_spec()` 命中空 dict → `default_variant: high` 永不生效 | §6 | variant 策略完全失效 |
| G4 | `default` 不是 opencode CLI 合法 variant 值（实测仅 `high|max|minimal`）。`projects.yaml.example` 写了 `default_variant: "default"`，一旦透传会报错 | §6 variant 表 | 透传 variant 前必须归一化：`default → 省略 flag` |
| G5 | 无规格 §2 的 `AGENTS.md`，OpenCodeWorker 不向 worktree 注入 AGENTS.md | §2 | opencode 会从 `--dir` 自动读 AGENTS.md；当前 worktree 里没有，worker 收不到硬规则 |
| G6 | 无规格 §3 的 `prompts/opencode_worker_prompt.md`（OpenCodeWorker 专用、含 identity/inputs/variants/18 条 hard rules/JSON 输出） | §3 | 当前 worker 收到的 prompt 是 `scheduler._worker_prompt()` 内联三行字符串（`scheduler.py:518-524`），既不读 `prompts/worker_prompt.md` 也不含 GLM-5.2 专属约束 |
| G7 | `scheduler._worker_prompt` 硬编码内联字符串，对所有 worker 一视同仁，没区分 worker 类型加载不同 prompt 文件 | §3 | 修复 G6 必须同时改这里 |
| G8 | `scheduler.py:293` 持久化 `route_variant=""`（恒空） | §6 | DB/审批学习拿不到 variant 信号 |
| G9 | `scripts/opencode-smoke-test.sh` 无"真实构造 + 不执行"的命令自检，只 grep help | §4 | 无法在 CI 阶段捕捉 variant/flag 构造回归 |
| G10 | 无 OpenCodeWorker 职责边界文档（规格 §7）的落地说明 | §7 | docs/OPENCODE_WORKER.md 已有定位，但未明确"不做什么"对照表 |

> 不算缺失（已由现有代码覆盖）：§5 路由分支、§4 禁止 `--dangerously-skip-permissions`、§7 分工。这些**沿用 Codex 既有实现**，不动。

---

## 3. 五阶段执行顺序（每阶段独立可回滚）

### Phase 1 — OpenCode 全局配置（最低风险，先做）
- **改**：`~/.config/opencode/opencode.jsonc`：在 `$schema` 下补 `"model": "opencode-go/glm-5.2"`。
- 不写死 `variant`、不加任何 bypass/skip 项。
- 校验：`opencode run --help` 仍正常；`cat` 确认 JSON 合法。
- 回滚：还原为单行 `$schema`。

### Phase 2 — OpenCodeWorker 专用 Prompt（纯加文件 + 一处只读加载）
- **新增**：`prompts/opencode_worker_prompt.md` —— 落规格 §3 全文（Worker Identity / Inputs / Allowed Variants `default|high|max` / 18 条 Hard Safety Rules / Task Execution Protocol / JSON 输出契约 / Important Boundaries）。
- **改**：`orchestrator/scheduler.py:_worker_prompt`（`scheduler.py:518`）—— 按 `route["selected_worker"]` 选 prompt 文件：`opencode` → 读 `prompts/opencode_worker_prompt.md` 并拼接 task/route；其余 worker 保持原内联字符串（行为不变）。
- **改**：`orchestrator/workers/opencode_worker.py:26` —— 写 `prompt.md` 时用上面同一份内容（已写 worker_dir，保持不变，只是内容来源改为专用 prompt）。
- 不动 `prompts/worker_prompt.md`（保留为通用回退）。
- 回滚：删新文件 + 还原 `_worker_prompt` 函数。

### Phase 3 — AGENTS.md 模板与 worktree 注入（安全侧加文件）
- **新增**：`config/AGENTS.md.template`（或 `prompts/AGENTS.md`）—— 落规格 §2 全文（OpenCodeWorker 角色 / 18 条 Hard Rules / Execution Rules / JSON 输出 / Failure Rules）。
- **新增**：`orchestrator/agents_md.py` —— `inject_agents_md(worktree: Path) -> Path`：把模板拷到 `worktree/AGENTS.md`（若已存在则跳过，记 warning）。
- **改**：`orchestrator/scheduler.py` 在 `prepare_worktree` 之后、worker.run 之前调用注入（`scheduler.py:297` 附近）。仅对 `opencode` worker 注入；claude/mimo 不注入（不影响其行为）。
- 不改业务路径、不读密钥。回滚：删模板与 `agents_md.py`，移除一行调用。

### Phase 4 — Variant 路由贯通（核心修复，改动面最小但跨 3 文件）
- **改** `orchestrator/router.py`：
  - `Route` 增加 `variant: str | None = None` 字段 + 进 `to_dict()`。
  - `plan_route` 在返回 OpenCodeWorker 路线时把已算出的 variant 放进 Route（`router.py:50-62`），并按规格 §6 表覆盖：explicit_glm52→`high`、medium/complex_coding→`high`、hard_bugfix→`max`、`default`（save_quota）→`None`（表示省略 flag）。
  - `_build_retry_chain` 已写死 `high→max`，保持，但把 inline 的 `"opencode_go_glm52"` model 串与 models.yaml key 对齐（见 G3）。
- **改** `orchestrator/env_profiles.py:model_spec` / `config.py:load_models`：增加 model key 别名归一（`opencode-go/glm-5.2` ↔ `opencode_go_glm52`），让 `model_spec("opencode-go/glm-5.2")` 能取到 `default_variant`。
- **改** `orchestrator/workers/opencode_worker.py:58-60`：variant 归一化——`None`/`default` → 不加 `--variant`；`high`/`max`/`minimal` → 透传；未知值 → 记 risk 并降级为省略 flag（永不传非法值给 CLI）。
- **改** `orchestrator/scheduler.py:293`：`route_variant` 取 `route.get("variant") or ""`，非空写入 DB。
- **改** `config/models.yaml.example` / `projects.yaml.example`：把 `default_variant: "default"` 注释为"等同于省略 `--variant`"，避免误传非法值。
- 回滚：还原 4 文件；Route 多出的 `variant=None` 字段对旧逻辑无副作用（向后兼容）。

### Phase 5 — smoke 自检 + 文档 + 测试补全（收尾，零业务风险）
- **改** `scripts/opencode-smoke-test.sh`：增加"构造命令但不执行"的 dry assert——用一段 Python 调 `orchestrator.workers.opencode_worker` 在 `dry_run=True` 下确认 mock 命令不含 `--dangerously-skip-permissions`、variant 归一正确。
- **新增** `tests/test_opencode_variant.py`：覆盖 variant 归一化（default→omit、high→透传、max→透传、非法→降级）+ Route.variant 透传 + AGENTS.md 注入路径。
- **新增** `tests/test_agents_md_injection.py`：模板拷贝、已存在则跳过。
- **改** `docs/OPENCODE_WORKER.md`：补规格 §3 的 variant 策略表与"不做什么"边界表（§7）。
- 回滚：删新测试文件，还原 smoke 脚本与文档。

---

## 4. 每阶段要修改/新增的文件清单

| 阶段 | 操作 | 文件 |
|---|---|---|
| P1 | 改 | `~/.config/opencode/opencode.jsonc` |
| P2 | 新增 | `prompts/opencode_worker_prompt.md` |
| P2 | 改 | `orchestrator/scheduler.py`（`_worker_prompt`） |
| P2 | 改 | `orchestrator/workers/opencode_worker.py`（prompt 写入内容来源，**非命令构造**） |
| P3 | 新增 | `config/AGENTS.md.template` |
| P3 | 新增 | `orchestrator/agents_md.py` |
| P3 | 改 | `orchestrator/scheduler.py`（注入调用一行） |
| P4 | 改 | `orchestrator/router.py`（Route + variant） |
| P4 | 改 | `orchestrator/env_profiles.py` + `orchestrator/config.py`（key 别名） |
| P4 | 改 | `orchestrator/workers/opencode_worker.py`（variant 归一） |
| P4 | 改 | `orchestrator/scheduler.py`（持久化 route_variant） |
| P4 | 改 | `config/models.yaml.example`、`config/projects.yaml.example`（注释语义） |
| P5 | 改 | `scripts/opencode-smoke-test.sh` |
| P5 | 新增 | `tests/test_opencode_variant.py`、`tests/test_agents_md_injection.py` |
| P5 | 改 | `docs/OPENCODE_WORKER.md` |

不创建：`~/repos/*`、`~/ai-orchestrator-v1` 软链（除非你额外批准）。
不修改：`.env.example`、`config/codex-mcp.config.example.toml` 里的 `/home/junye` 路径（登记为后续用户配置任务）。

---

## 5. 风险点

1. **P4 跨 3 个核心文件**（router / env_profiles / opencode_worker）改动，是实现规格 §6 的最小必要面，但有耦合。缓解：先加向后兼容字段（`variant=None`），再逐文件加测试，每步跑 `uv run pytest -q`。
2. **model key 别名改变 G3 行为**：之前 `model_spec` 对 GLM 查不到也没报错（cli_model 回退）。引入别名后 `default_variant` 才真正被读取——若 models.yaml 写成了非法值会 NEW 出错。缓解：归一化函数只接受白名单 `high|max|minimal|default|None`，其余记 warning + 省略 flag。
3. **AGENTS.md 注入覆盖风险**：若业务仓根已有 AGENTS.md，opencode 会读到仓内原版。缓解：注入逻辑"已存在则跳过 + 记 warning 到 artifacts"，绝不覆盖用户文件。
4. **worktree 跨文件系统**：业务仓在 `/mnt/c`（Windows FS），worktree 可能建在 Linux FS，`--dir` 指向 worktree 时 opencode 读写 AGENTS.md 走同一 FS 即可；无需额外处理，但需在 P3 测试用 tmp_path 验证。
5. **`default` variant 语义偏差**：规格 §6 把 `default` 当"save quota"，但 opencode CLI 无此 flag 值。本计划统一映射 `default→省略 flag`（等同规格 §1"variant 不写死在全局配置"）。需在文档明确，避免误解。
6. **遗留 `/home/junye` 硬编码**：不属本次任务，但 doctor / run-mcp 在本机会报路径不对。登记在 README/SECURITY 已有的"Manual Configuration Needed"之下，不静默改。
7. **不动 reviewer / pr / verifier**：确保 P2-P4 的改动不触碰审批/PR/验证分支；diff 须限制在 worker + router + scheduler prompt 层。

---

## 6. 测试计划

| 阶段 | 命令 | 期望 |
|---|---|---|
| 全程基线 | `cd <repo> && uv run pytest -q`（P0 起跑前先跑一次，记录 13 个测试绿） | 0 fails，作为回归基线 |
| P1 | `cat ~/.config/opencode/opencode.jsonc` + `opencode run --help` | JSON 合法、CLI 仍可用 |
| P2 | `uv run pytest -q tests/test_workers.py` | 现有 mock 测试仍绿；新增断言 opencode worker 收到 prompt 含 "OpenCodeWorker" 字样 |
| P3 | `uv run pytest -q tests/test_agents_md_injection.py` | 模板拷贝成功、已存在则跳过 |
| P4 | `uv run pytest -q tests/test_opencode_variant.py tests/test_router.py` | variant 归一与透传全绿；test_router 现有 14 断言不回归 |
| P5 | `bash scripts/opencode-smoke-test.sh` + 全量 `uv run pytest -q` | smoke 通过、全测试 绿 |
| 静态 | `uv run ruff check .` + `uv run mypy orchestrator` | 无新增 error（沿用 pyproject 既定 ruff/mypy） |
| 终态 dry-run | `uv run ai-dispatcher submit-task --project generic --goal "用 GLM-5.2 只读分析" --dry-run` | 生成 `route.json` 含 `variant` 字段、artifacts 含 `worker/prompt.md` 为专用 prompt、worktree 含 `AGENTS.md` |

真实 GLM 调用不在本次自动化内（需 OpenCode Go 登录/配额），仅在 doctor smoke 把"CLI 存在 + flag 合法"作为门槛。

---

## 7. 回滚方案

- 全仓改动均**增量**，无删除、无覆盖业务文件。
- 每阶段独立提交（后续若启用 git）。回滚粒度 = 单阶段。
- 具体可逆点：
  - P1：`opencode.jsonc` 还原为单行 `$schema`。
  - P2/P3：删新增文件 + `git revert` 对 `scheduler.py` / `opencode_worker.py` 的 hunk。
  - P4：`Route.variant` 默认 `None`，旧路径行为不变；别名函数失败时回退原"查空 dict"行为，可安全摘除。
  - P5：删新增测试、还原 smoke 脚本。
- 紧急退路：`uv run ai-dispatcher` 仍可 `--dry-run`，无真实 GLM 调用即无外部副作用。

---

## 8. 沿用 Codex 已实现代码（不改）

- `orchestrator/router.py` 的 6 条路由分支（§5 已对齐）—— P4 只补 variant 字段，分支逻辑不动。
- `orchestrator/workers/claude_code_worker.py` 拒 GLM 逻辑 + `tests/test_workers.py` hotpatch 测试。
- `orchestrator/constants.py` 禁止动作/禁止路径清单 + `risk_policy.scan_command` 链路（§4 禁止项已落实）。
- `orchestrator/approval_graph.py` / `state_machine.py` / `scheduler._build_retry_chain` 的 high→max 升级（§6 retry 部分已有）。
- `orchestrator/env_profiles.py` 的 per-subprocess env 隔离机制（README 已论证）。
- `orchestrator/mcp_server.py` + `config/codex-mcp.config.example.toml` 的单入口/审批模式（§7 Codex 入口已落实）。
- `orchestrator/verifier.py` / `reviewer.py` / `pr.py`（§7 Verifier / final review / PR Gate 全不动）。

---

## 9. 只做增量修改（不重写）

- `orchestrator/scheduler.py`：只改 `_worker_prompt`（按 worker 选 prompt）+ 注入 AGENTS.md 一行 + `route_variant` 取值一行；**不动** `_execute` 主流程、不动 retry/verify/review/PR 分支。
- `orchestrator/workers/opencode_worker.py`：只调整 prompt 内容来源与 variant 归一 4 行；命令构造骨架（`run -m ... --format json --dir ... --title ...`）保留。
- `orchestrator/router.py`：只给 `Route` 加字段并在 3 个 OpenCode 返回点填 variant；分支判断与 keyword 列表不动。
- `config/*.example`：只补注释/variant 语义，不删字段。
- `docs/`：只增补 OPENCODE_WORKER.md 的 variant 表与边界表，不改其他文档。

---

## 10. 执行前置确认（等你拍板）

1. 是否同意 **P1→P5 顺序**逐一执行，每阶段结束我停下汇报、等你确认再进下一阶段？
2. 是否需要建 `~/ai-orchestrator-v1 -> <repo>` 软链（让规格字面路径生效）？默认**不建**。
3. `config/AGENTS.md.template` 放 `config/` 还是 `prompts/`？默认 `config/`（与其它模板同目录）。
4. 是否在 P4 顺手把 `models.yaml` 的 `opencode_go_glm52` key 改名为 `opencode-go/glm-5.2` 以彻底消除 G3？默认**只加别名、不改 key**，保持向后兼容。

确认后我开始 Phase 1。