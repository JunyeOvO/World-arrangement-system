from __future__ import annotations


AGENT_LLM_COMBINATIONS: dict[tuple[str, str], str] = {
    ("claude_code", "deepseek_flash"): "claude code + deepseek V4 flash",
    ("claude_code", "deepseek_pro"): "claude code + deepseek V4 pro",
    ("claude_code", "mimo_v25"): "claude code + Mimo V2.5",
    ("claude_code", "mimo_v25_pro"): "claude code + Mimo V2.5 pro",
    ("opencode", "opencode-go/glm-5.2"): "opencode + GLM 5.2",
    ("opencode", "opencode_go_glm52"): "opencode + GLM 5.2",
    ("codex_review", "codex_reviewer"): "codex + GPT 5.5",
}


def agent_llm_name(agent: str, llm: str) -> str:
    return AGENT_LLM_COMBINATIONS.get((agent, llm), f"{agent} + {llm}")
