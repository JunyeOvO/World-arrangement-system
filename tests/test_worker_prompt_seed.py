from __future__ import annotations

from orchestrator.worker_prompt_seed import read_only_seed_context, seed_file_excerpt


def test_seed_file_excerpt_redacts_secret_like_values():
    text = "const API_KEY = 'sk-thismustberedacted123456';\nexport function boot() {}"

    excerpt = seed_file_excerpt(text)

    assert "API_KEY=[REDACTED]" in excerpt
    assert "sk-thismustberedacted" not in excerpt


def test_code_contract_seed_context_prioritizes_workarea_files(tmp_path):
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "state.js").write_text("export const state = {};\n", encoding="utf-8")
    (tmp_path / "js" / "three-work-area.js").write_text("export function resolveWorkArea() {}\n", encoding="utf-8")
    task = {
        "repo_path": str(tmp_path),
        "user_goal": "审计 selected workArea 到 3D scene 的数据契约",
    }

    context = read_only_seed_context(task, "code_contract_audit")

    assert "Seed files World selected for code_contract_audit" in context
    assert context.index("js/three-work-area.js") < context.index("README.md")
    assert "resolveWorkArea" in context
