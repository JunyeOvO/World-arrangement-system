from __future__ import annotations

from typing import Any

from .worker_prompt_seed import next_task_planning_seed_context, read_only_seed_context


def read_only_required_output_contract(task: dict[str, Any], *, read_only: bool) -> str:
    if not read_only:
        return ""
    profile = str(task.get("read_budget_profile") or "quick_triage").strip().lower()
    budget = task.get("read_budget") if isinstance(task.get("read_budget"), dict) else {}
    max_turns = budget.get("max_worker_turns") or "the configured"
    body = _profile_contract_body(profile)
    return (
        "\nRequired read-only output contract:\n"
        "- Before making any broad search or extra file read, keep this exact result template ready.\n"
        f"- You have at most {max_turns} worker turns; do not spend the final allowed turn on another Read/List/Search.\n"
        "- If you think 'I have enough data', immediately return the template instead of verifying one more detail.\n"
        "- If evidence is incomplete, still return a partial result; do not fail silently.\n"
        "- Always include changed_files=[] and needs_user=false unless you truly need user input.\n"
        "Template:\n"
        "```text\n"
        "status: success\n"
        "partial: <true|false>\n"
        f"profile: {profile}\n"
        f"{body}"
        "changed_files: []\n"
        "needs_user: false\n"
        "```\n"
    )


def worker_profile_strategy(task: dict[str, Any]) -> str:
    profile = str(task.get("read_budget_profile") or "").strip().lower()
    if profile == "quick_triage":
        seed_context = read_only_seed_context(task, profile)
        return (
            "Quick-triage early-output strategy:\n"
            "- Do not use Agent/subagent tools for this profile; keep the task bounded in the current worker.\n"
            "- Use the seeded files and evidence below before listing or searching the repo.\n"
            "- Read at most 2 files before drafting a provisional result.\n"
            "- After 2 file reads or one clear signal, stop broad exploration and write the best current conclusion.\n"
            "- The result must include: conclusion, evidence files, key risks, next step, and changed_files=[].\n"
            "- If evidence is incomplete, explicitly label the answer partial and return it instead of reading more files.\n"
            f"{seed_context}"
        )
    if profile == "code_contract_audit":
        seed_context = read_only_seed_context(task, profile)
        return (
            "Code-contract audit early-output strategy:\n"
            "- Do not use Agent/subagent tools for this profile; inspect only the contract path needed for this task.\n"
            "- Use the seeded files and evidence below before listing or searching the repo.\n"
            "- Read at most 3 files before drafting a contract hypothesis.\n"
            "- The first draft must include: suspected contract, producer, consumer, mismatch risk, evidence files, next file if needed, and changed_files=[].\n"
            "- After the draft exists, read at most 2 additional files only to confirm or reject that hypothesis.\n"
            "- If the budget is nearly exhausted, return the current hypothesis as a partial result with risks; do not continue searching.\n"
            f"{seed_context}"
        )
    if profile == "docs_review":
        return (
            "Docs-review early-output strategy:\n"
            "- Do not use Agent/subagent tools for this profile; keep the review to the most relevant docs/files.\n"
            "- Read at most 2 docs or config files before drafting a scorecard.\n"
            "- The scorecard must include: audience, missing setup/test/usage information, stale or risky claims, priority, and changed_files=[].\n"
            "- After the scorecard exists, read at most 2 additional files only to validate high-priority gaps.\n"
            "- If evidence is incomplete, return a partial scorecard with confidence and next checks instead of reading more files.\n"
        )
    if profile != "next_task_planning":
        return ""
    seed_context = next_task_planning_seed_context(task)
    return (
        "Next-task planning strategy:\n"
        "- Do not use Agent/subagent tools for this profile; keep reasoning in the current worker.\n"
        "- Do not run shell commands for this profile; use the seed evidence below first.\n"
        "- Read at most 3 additional files total, only when the seed evidence is insufficient.\n"
        "- After the first plausible next task candidate is identified, stop broad exploration and draft the final result.\n"
        "- The final summary may contain 1 to 3 candidates; one high-confidence candidate is better than timing out.\n"
        "- Each candidate must include target files, acceptance criteria, risk, recommended model route, and changed_files=[].\n"
        "- If evidence is incomplete, mark the candidate as partial and return status=partial or success with risks; do not continue searching.\n"
        f"{seed_context}"
    )


def _profile_contract_body(profile: str) -> str:
    if profile == "code_contract_audit":
        return (
            "- suspected_contract: <the data/API contract under review>\n"
            "- producer: <file/function or unknown>\n"
            "- consumer: <file/function or unknown>\n"
            "- mismatch_risk: <none/low/medium/high plus reason>\n"
            "- evidence_files: <1-5 paths already read>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
            "- next_step: <single bounded next action>\n"
        )
    if profile == "docs_review":
        return (
            "- audience: <developer/user/operator>\n"
            "- scorecard: <setup/test/usage/architecture status>\n"
            "- gaps: <highest priority gaps>\n"
            "- evidence_files: <1-5 paths already read>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
            "- next_step: <single bounded next action>\n"
        )
    if profile == "next_task_planning":
        return (
            "- candidate: <one high-confidence task is enough>\n"
            "- target_files: <likely files>\n"
            "- acceptance_criteria: <how Codex/user verifies it>\n"
            "- risk: <low/medium/high plus reason>\n"
            "- recommended_route: <worker/model/profile>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
        )
    return (
        "- conclusion: <current best answer, partial is acceptable>\n"
        "- evidence_files: <1-5 paths already read>\n"
        "- risks: <key risks or unknowns>\n"
        "- next_step: <single bounded next action>\n"
    )
