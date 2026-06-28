from orchestrator.router import plan_route


def test_docs_route_low_cost():
    route = plan_route({"user_goal": "更新 README 文档", "risk_level": "low"}, {})
    assert route.selected_model == "deepseek_pro"
    assert route.selected_worker == "claude_code"


def test_high_risk_route():
    """Hotpatch: high-risk routes to ClaudeCodeWorker + deepseek_pro (not GLM)."""
    route = plan_route({"user_goal": "重构鉴权中间件", "risk_level": "high"}, {})
    assert route.selected_model == "deepseek_pro"
    assert route.selected_worker == "claude_code"
    assert route.max_retries == 1


def test_multimodal_route():
    route = plan_route({"user_goal": "根据 UI 截图修复布局", "risk_level": "medium"}, {})
    assert route.selected_worker == "claude_code"
    assert route.selected_model == "mimo_v25_pro"


# ── New tests ──

def test_router_default_claude_code():
    """Default route should use ClaudeCodeWorker for routine tasks."""
    route = plan_route(
        {"user_goal": "fix a small typo in utils", "risk_level": "low"},
        {"project_id": "generic", "stack": ["python"]},
    )
    assert route.selected_worker == "claude_code"


def test_router_explicit_glm52_uses_opencode():
    """Explicit GLM-5.2 request should route to OpenCodeWorker."""
    route = plan_route(
        {"user_goal": "用 GLM-5.2 分析这段代码并修复bug", "risk_level": "medium"},
        {"project_id": "shiwu"},
    )
    assert route.selected_worker == "opencode"


def test_router_complex_coding_uses_opencode():
    """Complex coding escalates to OpenCodeWorker (V2: ClaudeCodeWorker prime + opencode escalation)."""
    route = plan_route(
        {"user_goal": "refactor the data layer", "risk_level": "medium", "task_type": "complex_coding"},
        {"project_id": "shiwu", "stack": ["android", "kotlin"]},
    )
    oc = [a for a in (route.to_dict().get("retry_chain") or []) if a.get("worker") == "opencode"]
    assert oc, "complex_coding must escalate to OpenCodeWorker in the retry chain"


def test_router_opencode_via_project_config():
    """Project configured with opencode worker should use OpenCodeWorker."""
    route = plan_route(
        {"user_goal": "add a new API endpoint", "risk_level": "medium"},
        {"project_id": "shiwu", "stack": ["android", "kotlin"], "default_worker": "opencode", "default_model": "opencode-go/glm-5.2"},
    )
    assert route.selected_worker == "opencode"


# ── Hotpatch-required tests ──

def test_default_docs_routes_to_claude_deepseek():
    """Hotpatch: default docs task → ClaudeCodeWorker + deepseek_pro."""
    route = plan_route(
        {"user_goal": "更新 README 文档", "risk_level": "low"},
        {},
    )
    assert route.selected_worker == "claude_code"
    assert route.selected_model == "deepseek_pro"


def test_simple_bug_routes_to_claude_deepseek():
    """Hotpatch: simple bug → ClaudeCodeWorker + deepseek_pro."""
    route = plan_route(
        {"user_goal": "修复 utils 中的 typo", "risk_level": "low"},
        {"project_id": "generic"},
    )
    assert route.selected_worker == "claude_code"
    assert route.selected_model == "deepseek_pro"


def test_explicit_glm52_routes_to_opencode():
    """Hotpatch: explicit GLM-5.2 → OpenCodeWorker only."""
    route = plan_route(
        {"user_goal": "用 GLM-5.2 修复这段代码", "risk_level": "medium"},
        {},
    )
    assert route.selected_worker == "opencode"
    assert route.selected_model == "opencode-go/glm-5.2"


def test_complex_coding_routes_to_opencode_glm52():
    """Hotpatch: complex_coding → OpenCodeWorker + GLM-5.2 (via escalation chain in V2)."""
    route = plan_route(
        {"user_goal": "大规模重构整个数据层", "risk_level": "medium", "task_type": "complex_coding"},
        {},
    )
    oc = [a for a in (route.to_dict().get("retry_chain") or []) if a.get("worker") == "opencode"]
    assert oc, "complex_coding must escalate to OpenCodeWorker"
    assert any(a.get("model") == "opencode-go/glm-5.2" for a in oc)


def test_hard_bugfix_routes_to_opencode_glm52():
    """Hotpatch: hard_bugfix → OpenCodeWorker + GLM-5.2."""
    route = plan_route(
        {"user_goal": "修复 race condition 崩溃", "risk_level": "high", "task_type": "hard_bugfix"},
        {},
    )
    assert route.selected_worker == "opencode"
    assert route.selected_model == "opencode-go/glm-5.2"


def test_high_risk_routes_to_claude_not_glm():
    """Hotpatch: high-risk tasks route to ClaudeCodeWorker (never GLM though Claude)."""
    route = plan_route(
        {"user_goal": "重构鉴权中间件", "risk_level": "high"},
        {},
    )
    assert route.selected_worker == "claude_code"
    # Model must NOT be a GLM variant
    assert "glm" not in route.selected_model.lower()
    assert route.selected_model == "deepseek_pro"


def test_project_with_glm_default_sanitized():
    """Hotpatch: if project has GLM as default model, override to deepseek_pro."""
    route = plan_route(
        {"user_goal": "add feature flag", "risk_level": "medium"},
        {"project_id": "old_project", "default_model": "glm_advanced", "default_worker": "claude_code", "stack": ["react"]},
    )
    # Must be sanitized away from GLM
    assert "glm" not in route.selected_model.lower()
    assert route.selected_worker == "claude_code"


def test_multimodal_routes_to_claude_mimo():
    """Hotpatch: multimodal tasks → ClaudeCodeWorker + MiMo."""
    route = plan_route(
        {"user_goal": "分析 UI 截图并修复布局", "risk_level": "medium"},
        {},
    )
    assert route.selected_worker == "claude_code"
    assert route.selected_model == "mimo_v25_pro"


def test_no_hermes_route_exists():
    """Hotpatch: no Hermes route should ever be selected."""
    import json
    tasks = [
        {"user_goal": "普通任务", "risk_level": "medium"},
        {"user_goal": "用 GLM-5.2 做代码审查", "risk_level": "high"},
        {"user_goal": "修复简单bug", "risk_level": "low", "task_type": "simple_bugfix"},
    ]
    for task in tasks:
        route = plan_route(task, {})
        assert "hermes" not in route.selected_worker.lower()
        assert "hermes" not in json.dumps(route.to_dict()).lower()
