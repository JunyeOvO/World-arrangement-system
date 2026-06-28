# 全局项目管理

## 注册方式

### 1. 全局注册表 `~/.ai-orchestrator/projects.yaml`

```yaml
projects:
  my_project:
    project_id: "my_project"
    name: "My Project"
    repo: "/home/junye/repos/my-project"
    default_branch: "main"
    pr_base_branch: "main"
    stack: ["python", "fastapi"]
    test_commands: ["pytest -q"]
    build_commands: []
    forbidden_paths: [".env", "secrets/**"]
    default_worker: "claude_code"
    default_model: "deepseek_pro"
    allow_auto_pr: false
    allow_remote_push: false
```

### 2. 项目内标记 `.ai-project.yaml`

```yaml
project_id: my_project
orchestrator: ai_dispatcher
default_worker: claude_code
glm52_worker: opencode
auto_pr: true
auto_merge: false
```

## 项目识别顺序

```
1. 当前目录 .ai-project.yaml          → confidence=1.0
2. ~/.ai-orchestrator/projects.yaml   → confidence=0.9
   中 repo 绝对路径匹配
3. git remote URL 匹配                → confidence=0.7
4. 目录名 fuzzy match                 → confidence=0.5
5. 找不到 → NEEDS_USER                → confidence=0.0
```

## 使用

### 通过 Codex MCP

```
使用 ai_dispatcher.submit_current_project_task
任务: 修复 README 中的安装说明
risk_level: low
auto_execute: true
```

### 通过 CLI

```bash
ai-dispatcher list-projects
ai-dispatcher detect-project --repo-path /path/to/repo
ai-dispatcher submit-task --project my_project --goal "fix bug" --risk-level medium
```

## Windows/WSL 路径注意事项

- `projects.yaml` 中 `repo` 字段使用 WSL 路径（如 `/home/junye/repos/...`）
- Windows 路径需转换为 `/mnt/c/Users/...` 格式
- `.ai-project.yaml` 放在仓库根目录即可，跨平台兼容
