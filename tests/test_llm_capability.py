from orchestrator.llm_capability import capability_profile, env_for_capability, normalize_capability_tier


def test_capability_tier_normalization_from_intensity():
    assert normalize_capability_tier(None, "medium") == "default"
    assert normalize_capability_tier(None, "high") == "high"
    assert normalize_capability_tier(None, "max") == "max"
    assert normalize_capability_tier("bogus", "low") == "default"


def test_glm_tiers_map_to_opencode_variants():
    assert capability_profile("opencode-go/glm-5.2", "default")["variant"] is None
    assert capability_profile("opencode-go/glm-5.2", "high")["variant"] == "high"
    assert capability_profile("opencode-go/glm-5.2", "max")["variant"] == "max"


def test_non_variant_capabilities_use_top_context_standard():
    for model in ["deepseek_flash", "deepseek_pro", "mimo_v25", "mimo_v25_pro", "codex_reviewer"]:
        profile = capability_profile(model, "max")
        assert profile["tier"] == "max"
        assert profile["context_policy"] == "top"
        assert profile["context_budget"] == "max_available"
        assert profile["prompt_budget"] == "max_available"


def test_capability_env_exports_standard_fields():
    env = env_for_capability(capability_profile("deepseek_pro", "high"))
    assert env["AI_ORCHESTRATOR_CAPABILITY_TIER"] == "high"
    assert env["AI_ORCHESTRATOR_CONTEXT_POLICY"] == "top"
    assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
