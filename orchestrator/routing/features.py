"""FeatureExtractor: extract structured features from a task dict."""
from __future__ import annotations

from typing import Any

from ..router_v3 import classify_task_shape
from .schema import TaskFeatures

# ── Path kind patterns ──
_DOCS_PATHS = {"readme.md", "readme", "docs/", "*.md", "*.markdown", "changelog.md", "contributing.md"}
_TEST_PATHS = {"tests/", "test_", "_test", "spec/", "__tests__"}
_CONFIG_PATHS = {".env", ".env.", "secrets/", "keys/", "credentials/", "*.pem", "*.key"}
_PROD_PATHS = {"prod", "deploy/prod", "infra/prod", "database/migrations/prod"}

# ── Action keywords ──
_DOCS_ACTIONS = {"文档", "说明", "注释", "readme", "markdown", "md", "doc", "document", "write", "添加说明", "更新文档", "写说明", "update doc", "add doc"}
_ANALYZE_ACTIONS = {"分析", "检查", "审查", "review", "audit", "diagnose", "定位", "查看", "explore", "inspect"}
_FIX_ACTIONS = {"修复", "fix", "bug", "报错", "error", "crash", "failing", "修正", "改正"}
_REFACTOR_ACTIONS = {"重构", "refactor", "restructure", "redesign", "重写", "rewrite"}
_TEST_ACTIONS = {"测试", "test", "pytest", "unit test", "e2e", "覆盖率", "coverage"}
_IMPLEMENT_ACTIONS = {
    "实现", "新增", "开发", "add feature", "build", "create",
    "add", "modify", "change", "update", "edit",
    "创建", "添加", "增加", "加入", "修改", "修改代码", "改", "写", "编写", "撰写",
}

# ── Object keywords ──
_UI_OBJECTS = {"ui", "页面", "布局", "组件", "screenshot", "截图", "design", "设计", "前端", "frontend", "样式", "style", "css"}
_AUTH_OBJECTS = {"auth", "登录", "认证", "鉴权", "token", "session", "oauth", "jwt", "password", "密码"}
_DATABASE_OBJECTS = {"database", "db", "migration", "数据库", "迁移", "sql", "table", "schema", "索引", "index"}
_INFRA_OBJECTS = {"deploy", "prod", "docker", "k8s", "nginx", "ci", "cd", "pipeline", "infra", "部署"}
_ARCHITECTURE_OBJECTS = {"架构", "architecture", "模块边界", "系统设计", "module", "模块"}

# ── Explicit model request keywords ──
_GLM_KEYWORDS = {"glm", "glm-5.2", "glm52", "opencode", "用glm", "使用glm", "use glm", "using glm", "open code"}

# ── Multimodal keywords ──
_MULTIMODAL_KEYWORDS = {"截图", "图片", "image", "screenshot", "video", "音频", "pdf", "design", "设计稿", "photo", "照片", "画面", "picture", "graphic"}

# ── High-risk signal keywords ──
_RISK_SIGNALS = {"auth", "token", "session", "payment", "database", "migration", "prod", "infra", "deploy", "认证", "鉴权", "支付", "数据库", "迁移", "部署"}

# ── Blocked signal keywords ──
_BLOCKED_SIGNALS = {".env", ".env.", "secrets/", "keys/", "credentials/", "*.pem", "*.key", "rm -rf /", "git push --force", "gh pr merge", "drop database", "truncate", "chmod -R 777 /", "curl | sh", "wget | sh"}


def extract_features(task: dict[str, Any], project: dict[str, Any] | None = None) -> TaskFeatures:
    """Extract structured features from a raw task dict."""
    goal = str(task.get("user_goal", ""))
    goal_lower = goal.lower()
    keywords = [w.strip().lower() for w in goal_lower.replace("、", " ").replace("，", " ").replace("。", " ").split() if len(w.strip()) > 0]

    # Target paths
    target_paths = list(task.get("target_paths", []))
    if not target_paths:
        for kw in keywords:
            if kw.endswith(".md") or "/" in kw:
                target_paths.append(kw)

    # Path kinds
    path_kinds = _classify_paths(target_paths, goal_lower)

    # Actions
    actions = _classify_actions(goal_lower, keywords, task)

    # Objects
    objects = _classify_objects(goal_lower, keywords)

    # Explicit model request
    explicit_model_request = None
    if any(kw in goal_lower for kw in _GLM_KEYWORDS):
        explicit_model_request = "glm52"

    # Multimodal
    requires_multimodal = any(kw in goal_lower for kw in _MULTIMODAL_KEYWORDS)

    # Risk signals
    risk_signals = [kw for kw in keywords if kw in _RISK_SIGNALS]

    # Blocked signals
    blocked_signals = [sig for sig in _BLOCKED_SIGNALS if sig in goal_lower]

    features = TaskFeatures(
        goal_lower=goal_lower,
        keywords=keywords,
        target_paths=target_paths,
        path_kinds=path_kinds,
        actions=actions,
        objects=objects,
        explicit_model_request=explicit_model_request,
        requires_multimodal=requires_multimodal,
        risk_signals=risk_signals,
        blocked_signals=blocked_signals,
        task_type=str(task.get("task_type", "")),
        risk_level=str(task.get("risk_level", "medium")),
    )
    features.task_shape = classify_task_shape(task, features, None)
    return features


def _classify_paths(paths: list[str], goal_lower: str) -> list[str]:
    kinds = []
    for p in paths:
        pl = p.lower()
        if any(doc in pl for doc in _DOCS_PATHS):
            kinds.append("docs")
        if any(test in pl for test in _TEST_PATHS):
            kinds.append("tests")
        if any(conf in pl for conf in _CONFIG_PATHS):
            kinds.append("config")
        if any(prod in pl for prod in _PROD_PATHS):
            kinds.append("prod")
    # Detect from goal
    if not kinds:
        if "readme" in goal_lower or "文档" in goal_lower:
            kinds.append("docs")
        if "测试" in goal_lower or "test" in goal_lower:
            kinds.append("tests")
    return kinds if kinds else ["unknown"]


def _classify_actions(goal_lower: str, keywords: list[str], task: dict[str, Any]) -> list[str]:
    actions = []
    task_type = str(task.get("task_type", ""))

    if any(act in goal_lower for act in _DOCS_ACTIONS):
        actions.append("docs")
    if any(act in goal_lower for act in _ANALYZE_ACTIONS):
        actions.append("analyze")
    if any(act in goal_lower for act in _FIX_ACTIONS) or task_type == "simple_bugfix":
        actions.append("fix")
    if any(act in goal_lower for act in _REFACTOR_ACTIONS) or task_type == "large_refactor":
        actions.append("refactor")
    if any(act in goal_lower for act in _TEST_ACTIONS):
        actions.append("test")
    if any(act in goal_lower for act in _IMPLEMENT_ACTIONS):
        actions.append("implement")

    return actions if actions else ["unknown"]


def _classify_objects(goal_lower: str, keywords: list[str]) -> list[str]:
    objects = []

    if any(obj in goal_lower for obj in _UI_OBJECTS):
        objects.append("ui")
    if any(obj in goal_lower for obj in _AUTH_OBJECTS):
        objects.append("auth")
    if any(obj in goal_lower for obj in _DATABASE_OBJECTS):
        objects.append("database")
    if any(obj in goal_lower for obj in _INFRA_OBJECTS):
        objects.append("infra")
    if any(obj in goal_lower for obj in _ARCHITECTURE_OBJECTS):
        objects.append("architecture")

    # Docs object
    if "readme" in goal_lower or "文档" in goal_lower or "doc" in keywords:
        if "docs" not in objects:
            objects.append("docs")

    return objects if objects else ["general"]
