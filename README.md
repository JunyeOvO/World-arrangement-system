# World 系统

> 兼容说明：本仓库早期名称为 ai-orchestrator-v1，CLI 仍保留 `ai-dispatcher`。

World 系统是一个以 Codex 为入口、World Core（MCP Orchestrator）为调度核心，连接 Claude Code、OpenCode、Codex Review 等 Agent 与固定 LLM 组合的多模型全自动开发中枢。

用户只需在 Codex 中输入自然语言任务，World Core（MCP `ai_dispatcher`）自动完成项目识别、模型路由、worktree 隔离、worker 执行、测试、World Review、PR 或 patch 交付。

安全边界：**可以自动执行、自动测试、自动生成 diff、自动 review、自动创建 PR；永远不自动 merge。**

## Layout

```text
orchestrator/         Python package
config/               user-level config templates
profiles/             provider env profile examples, no real keys
prompts/              worker/reviewer prompts
schemas/              JSON Schema contracts
scripts/              install, doctor, MCP and dry-run helpers
tests/                pytest suite
docs/                 architecture, SOP, security, routing, Codex usage
```

Key documents:

- `docs/WORLD_SYSTEM_OVERVIEW.md`
- `docs/CODEX_ENTRY.md`
- `docs/LIGHTWEIGHT_DEPLOYMENT.md`
- `docs/ROUTER_V2.md`
- `docs/ADAPTIVE_PARALLELISM.md`
- `docs/WORKER_CONTRACT.md`
- `docs/OPENCODE_WORKER.md`
- `docs/MODEL_ROUTING.md`

## Install

```bash
cd ai-orchestrator-v1
uv sync --dev
mkdir -p ~/.ai-orchestrator/runs
mkdir -p ~/.world
cp config/projects.yaml.example ~/.ai-orchestrator/projects.yaml
cp config/models.yaml.example ~/.ai-orchestrator/models.yaml
cp config/policies.yaml.example ~/.ai-orchestrator/policies.yaml
```

Edit `~/.ai-orchestrator/projects.yaml` so each `repo` points to a real git repository.

World vNext runtime artifacts use `WORLD_HOME` when available and default to `~/.world`. Keep provider keys and runtime profiles outside business repositories.

## Codex MCP Config

Copy `config/codex-mcp.config.example.toml` into your user-level Codex config and adjust the project path:

```toml
[mcp_servers.ai_dispatcher]
command = "uv"
args = ["run", "--project", "/home/junye/ai-orchestrator-v1", "python", "-m", "orchestrator.mcp_server"]
```

Do not add API keys to this repository.

## Dry Run

```bash
uv run ai-dispatcher doctor
uv run pytest -q
uv run ai-dispatcher submit-task --project generic --goal "只读分析项目结构" --dry-run
```

Dry-run mode creates task rows and artifacts without calling real worker CLIs or requiring provider keys.

## WSL-Only Worker Commands

World Core may run from Windows/Codex, but Claude Code and OpenCode workers are WSL-only. Real worker execution defaults to:

```powershell
wsl -e claude
wsl -e opencode
```

If your WSL environment uses different command names, set overrides before running real workers:

```bash
export AI_CLAUDE_CMD=claude
export AI_OPENCODE_CMD=/path/to/opencode
```

From Windows PowerShell, keep the WSL command wrapper:

```powershell
$env:AI_CLAUDE_CMD = "wsl -e claude"
$env:AI_OPENCODE_CMD = "wsl -e opencode"
```

`ai-dispatcher doctor` reads these overrides and checks the command inside WSL, not only `wsl.exe`.

## Agent + LLM Combinations

World Router 只使用以下组合：

- claude code + deepseek V4 flash
- claude code + deepseek V4 pro
- claude code + Mimo V2.5
- claude code + Mimo V2.5 pro
- opencode + GLM 5.2
- codex + GPT 5.5

## DeepSeek, MiMo, and GLM-5.2

Do not solve provider switching by rewriting global `~/.claude/settings.json` for every task. That breaks concurrent runs.

For Claude Code only, keep one env profile per provider in `profiles/` and map each Claude-backed logical model in `config/models.yaml` to an `env_profile`. The Claude worker loads the selected profile only for that subprocess. This allows one Claude Code worker invocation to use DeepSeek while another uses MiMo without cross-contaminating environment variables.

Claude Code is only allowed to use DeepSeek or MiMo. GLM-5.2 must go through OpenCode with `opencode-go/glm-5.2`. OpenCode provider authentication/configuration is owned by OpenCode itself; World does not inject API keys or provider env profiles into OpenCode subprocesses. MiMo V2.5 and MiMo V2.5 Pro run through Claude Code, not a separate MiMo worker.

## Control Layer

Real worker calls run under a World control layer. Each task writes:

- `control/process.json`: managed process PID, status, timeout, redacted command, stdout/stderr paths.
- `control/heartbeat.json`: last seen time and elapsed seconds while the worker is running.
- `control/cancel.requested`: durable cancellation request written by `cancel-task`.

Use `ai-dispatcher get-task-control --task-id <id>` to inspect whether a task is running, timed out, cancelled, or finished. `cancel-task` now writes the cancel request and terminates the worker process tree.

## Daily Use

Ask Codex to use `ai_dispatcher.submit_task` or `ai_dispatcher.submit_current_project_task`.

Example:

```text
使用 ai_dispatcher.submit_task。
项目：generic
任务：修复 README 中的安装说明并运行测试。
风险等级：low
auto_execute=true
auto_pr=true
不要自动合并。
```

## Manual Configuration Needed

- OpenAI / Codex login if using Codex review.
- DeepSeek API key if using DeepSeek through Claude Code.
- MiMo API key if using Claude Code + MiMo V2.5 or Claude Code + MiMo V2.5 Pro.
- OpenCode provider access configured in OpenCode itself if using GLM-5.2 through OpenCodeWorker.
- GitHub CLI login if enabling PR creation.
- Real project paths in `~/.ai-orchestrator/projects.yaml`.

## Failure Handling

- Missing worker CLI: dry-run/mock worker path still works; doctor reports missing binary.
- Tests fail: task becomes `FAILED_FINAL`; no PR is created.
- Codex review fails: no PR is created.
- Forbidden path changes: task becomes `FAILED_FINAL`.
- `gh` unavailable or remote push disabled: system returns `COMPLETED_WITH_PATCH`.
