# Windows / WSL 混合部署指南

## 推荐架构

```
Windows 侧:
  - Codex 客户端（唯一用户入口）
  - VS Code / Android Studio / Unity / 浏览器
  - Claude Code（用于实现和维护系统本身）

WSL 侧:
  - ~/ai-orchestrator-v1/           # 系统实现
  - ~/.ai-orchestrator/             # 运行时配置和数据
  - ~/repos/*                       # 被编排的项目
  - opencode CLI                    # OpenCodeWorker 执行
  - claude CLI                      # ClaudeCodeWorker 执行
  - git / gh                        # 版本控制和 PR
  - python / uv / pytest            # 测试环境
```

## 安装

```bash
# WSL 中
cd ~/ai-orchestrator-v1
uv sync --all-extras

# 复制配置模板
cp config/projects.yaml.example ~/.ai-orchestrator/projects.yaml
cp config/models.yaml.example ~/.ai-orchestrator/models.yaml
cp config/policies.yaml.example ~/.ai-orchestrator/policies.yaml

# 编辑 projects.yaml 填入真实仓库路径
```

## Codex MCP 注册

在 `~/.codex/config.toml` 中添加：

```toml
[mcp_servers.ai_dispatcher]
command = "uv"
args = ["run", "--project", "/home/junye/ai-orchestrator-v1", "python", "-m", "orchestrator.mcp_server"]
```

## WSL HTTP MCP（备选）

如果 Codex 在 Windows 侧通过 HTTP 连接 WSL 的 MCP：

```toml
[mcp_servers.ai_dispatcher]
url = "http://localhost:8083/mcp"
```

WSL 中启动 MCP Server:
```bash
uv run ai-dispatcher-mcp
```

## 路径映射

| Windows | WSL |
|---------|-----|
| `C:\Users\fujunye\...` | `/mnt/c/Users/fujunye/...` |
| 不可用于 projects.yaml repo 字段 | 使用 `/home/junye/repos/...` |

## Worker 命令

如果 Worker CLI 在 WSL 中运行但被 Windows 侧调用：

```powershell
$env:AI_CLAUDE_CMD = "wsl -e claude"
$env:AI_OPENCODE_CMD = "wsl -e opencode"
```

## 常见问题

1. **`uv: command not found` in WSL** — 安装 uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **MCP 连接超时** — 检查 Windows 防火墙、WSL 网络转发
3. **opencode 不可用** — 运行 `scripts/opencode-smoke-test.sh` 诊断
4. **路径问题** — 所有 `projects.yaml` 中 `repo` 使用 WSL/Linux 绝对路径
