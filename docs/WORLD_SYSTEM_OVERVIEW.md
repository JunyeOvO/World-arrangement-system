# World 系统概述

> 兼容说明：本仓库早期名称为 ai-orchestrator-v1。

## 定位

World 系统是一个以 Codex 为入口、MCP Orchestrator 为调度核心，连接 Claude Code、OpenCode、Codex Review 等 Agent 与固定 LLM 组合的多模型全自动开发中枢。

## 架构

```
Codex (用户入口)
  │
  ▼
World CLI (ai-dispatcher)
  │
  ▼
World Core (MCP Orchestrator)
  ├─ World Router ──→ 任务路由到最佳 Agent + LLM
  ├─ World Guard  ──→ 安全审批 + 风险策略
  ├─ World Workers ──→ Claude Code / OpenCode
  ├─ World Review ──→ Codex / GPT-5.5 最终审查
  └─ World Registry ──→ 项目检测与自适应
        │
        ▼
World Workbench (隔离 worktree + artifacts)
```

## Agent + LLM 组合

| 组合 | 内部 Agent | 内部 LLM key | 职责 |
|------|------------|--------------|------|
| claude code + deepseek V4 flash | `claude_code` | `deepseek_flash` | 低成本快速任务 |
| claude code + deepseek V4 pro | `claude_code` | `deepseek_pro` | 默认执行：文档、测试、普通 coding |
| claude code + Mimo V2.5 | `claude_code` | `mimo_v25` | 多模态/UI/设计稿理解 |
| claude code + Mimo V2.5 pro | `claude_code` | `mimo_v25_pro` | 多模态到代码、高强度 MiMo coding |
| opencode + GLM 5.2 | `opencode` | `opencode-go/glm-5.2` | 复杂编码、hard bugfix、大重构 |
| codex + GPT 5.5 | `codex_review` | `codex_reviewer` | World Review |

## 安全边界

- ClaudeCodeWorker 不接 GLM
- GLM-5.2 只走 OpenCodeWorker
- MiMo V2.5 / V2.5 Pro 只通过 Claude Code，不作为独立 Worker
- 不自动 merge
- 不引入 Hermes
