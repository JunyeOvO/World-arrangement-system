# Dynamic Approval Graph

## 目标

让系统学习用户审批习惯，减少低风险重复任务打扰，但不能削弱硬安全边界。

```
重复安全任务 → 越来越自动
新任务 → 正常确认
高风险任务 → 永远人工确认
危险任务 → 永远阻断
所有任务 → 可解释、可审计、可撤销
```

## 审批模式

| 模式 | 行为 | 触发条件 |
|------|------|---------|
| **AUTO_SILENT** | 自动执行，不打扰 | 低风险 + 高信任 learned pattern |
| **AUTO_WITH_SUMMARY** | 自动执行，简短摘要 | 低风险默认 |
| **SOFT_APPROVAL** | Codex 确认一次 | 中风险默认 |
| **HARD_APPROVAL** | 显示计划，必须用户批准 | 高风险 / 复杂任务 |
| **BLOCKED** | 直接阻断 | 硬风险（forbidden path/command） |

## 硬风险（不可学习）

以下永远不可自动放行：

```
路径: .env, .env.*, secrets/**, keys/**, credentials/**,
      infra/prod/**, deploy/prod/**, database/migrations/prod/**,
      *.pem, *.key

命令: git push --force, rm -rf /, drop database, truncate,
      chmod -R 777 /, curl | sh, --dangerously-skip-permissions

关键词: auth, payment, prod, deployment, database migration, secret
```

## trust_score 规则

- 初始值: 0.5
- 成功 + tests_passed + codex_review_approved → 增加
- 失败 → 小幅降低
- **rollback → 大幅降低**（-2.0 权重）
- tests_passed=false → 不增加
- codex_review_approved=false → 不增加
- trust_score >= 0.7 → 可建议 AUTO 模式

## 学习原则

只能从真实结果学习：

```
✅ 用户 approve / reject
✅ PR merged / closed
✅ rollback
✅ Codex review pass / reject
✅ tests pass / fail
✅ incident

❌ 模型自评（GLM 说安全、OpenCode 说完成、DeepSeek 说 confident）
```

## MCP 工具

| 工具 | 用途 |
|------|------|
| `get_approval_decision` | 预检审批模式 |
| `approve_task` | 用户批准任务 |
| `reject_task` | 用户拒绝任务 |
| `list_learned_rules` | 查看已学规则 |
| `revoke_learned_rule` | 撤销规则 |
| `explain_approval` | 解释决策理由 |
| `list_policy_suggestions` | 查看策略建议 |
| `approve_policy_suggestion` | 批准建议 |
| `reject_policy_suggestion` | 拒绝建议 |

## 示例决策流程

```
任务: "fix typo in README" (low risk, docs)
  → 检查硬风险: 无
  → 检查 learned pattern: trust_score=0.85, task_type=docs
  → 决策: AUTO_SILENT

任务: "add payment integration" (high risk, complex_coding)
  → 检查硬风险: "payment" 命中
  → 决策: BLOCKED (hard-risk keyword)
  → 建议: 修改任务避免 direct payment 操作

任务: "refactor utils.py" (medium risk, routine_coding)
  → 检查硬风险: 无
  → 检查 learned pattern: trust_score=0.55（不足）
  → 决策: SOFT_APPROVAL
```
