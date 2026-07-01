# World 系统命名规范

## 正式名称

中文：World 系统  
英文：World System

## 一句话定位

World 系统是一个以 Codex 为入口、World Core 为调度核心，连接 Claude Code、OpenCode、Codex Review 等执行与审查能力的本地受控执行后端。

## 模块命名

| World 名称 | 技术实现 | 说明 |
|---|---|---|
| World Core | Orchestrator | 调度核心：路由、审批、状态机、测试、PR Gate |
| World Router | Router V2 | 可解释任务路由系统 |
| World Guard | ApprovalGraph / RiskPolicy | 安全审批与风险策略 |
| World Workers | Claude Code / OpenCode | 执行 Agent 层 |
| World Review | Codex final review | 最终审查 |
| World Registry | Adaptive Project Layer | 项目注册与自适应 |
| World Workbench | worktree / artifacts / diff | 隔离工作区 |
| World CLI | ai-dispatcher | 命令行入口 |

## 兼容说明

本项目早期名称为 ai-orchestrator-v1。  
当前阶段保留旧 CLI、包名和 MCP tool 名称，避免破坏现有自动化链路。

保留项：
- `ai-dispatcher` CLI 命令
- `orchestrator` Python package
- MCP tool 名 (`submit_task`, `submit_current_project_task`, etc.)
- Worker 类名 (`ClaudeCodeWorker`, `OpenCodeWorker`)
