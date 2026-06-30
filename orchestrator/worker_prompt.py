from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import code_root


_OPENCODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "opencode_worker_prompt.md"
_CLAUDE_CODE_WORKER_PROMPT_PATH = code_root() / "prompts" / "claude_code_worker_prompt.md"


def build_worker_prompt(
    task: dict[str, Any],
    route: dict[str, Any],
    *,
    task_requires_diff: Callable[[dict[str, Any]], bool],
) -> str:
    worker = str(route.get("selected_worker", "")).lower()
    read_only = not task_requires_diff(task)
    read_only_completion_rule = ""
    if read_only:
        read_only_completion_rule = (
            "Read-only completion rule: produce a concise partial result before the read budget is exhausted. "
            "If you are near the turn or time limit, stop exploring and return the best current answer with "
            "changed_files=[] instead of making more tool calls.\n"
        )
    required_output = _read_only_required_output_contract(task, read_only=read_only)
    profile_strategy = _worker_profile_strategy(task)
    project_memory = _project_memory_section(task)
    task_section = (
        f"\n\n## Task Context\n\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        f"Worktree: {task.get('worktree_path', '')}\n"
        f"Risk level: {task.get('risk_level', 'medium')}\n"
        f"Test commands: {json.dumps(task.get('test_commands', []), ensure_ascii=False)}\n"
        f"Build commands: {json.dumps(task.get('build_commands', []), ensure_ascii=False)}\n"
        f"Forbidden paths: {json.dumps(task.get('forbidden_paths', []), ensure_ascii=False)}\n"
        f"Task mode: {task.get('task_mode', 'patch')}\n"
        f"Expected diff: {json.dumps(task.get('expected_diff', True), ensure_ascii=False)}\n"
        f"Verification policy: {task.get('verification_policy', 'full')}\n"
        f"Read budget profile: {task.get('read_budget_profile', 'quick_triage')}\n"
        f"Read budget: {json.dumps(task.get('read_budget', {}), ensure_ascii=False)}\n"
        "Do not read run artifacts outside the worktree; this prompt is the authoritative task context.\n"
        "World Core will run the listed verification commands after you return; do not spend many turns on full-suite testing.\n"
        "Respect the task mode, expected diff, verification policy, and read budget before exploring more files.\n"
        f"{read_only_completion_rule}"
        f"{required_output}"
        f"{project_memory}"
        f"{profile_strategy}"
        "Return changed_files, summary, test_suggestions, risks, needs_user."
    )
    if task.get("vision_observation"):
        task_section += (
            "\n\n## Vision Observation\n\n"
            "Use this MiMo direct-API observation as visual context. Do not call `claude --file`.\n"
            f"{json.dumps(task['vision_observation'], ensure_ascii=False, indent=2)}\n"
        )
    if worker == "opencode" and _OPENCODE_WORKER_PROMPT_PATH.exists():
        return _OPENCODE_WORKER_PROMPT_PATH.read_text(encoding="utf-8").rstrip() + task_section
    if worker == "claude_code" and _CLAUDE_CODE_WORKER_PROMPT_PATH.exists():
        return _CLAUDE_CODE_WORKER_PROMPT_PATH.read_text(encoding="utf-8").rstrip() + task_section
    return (
        "You are a background coding worker. Do not push, merge, or edit forbidden paths.\n"
        f"Task: {task['user_goal']}\n"
        f"Route: {json.dumps(route, ensure_ascii=False)}\n"
        "Return changed_files, summary, test_suggestions, risks."
    )


def _project_memory_section(task: dict[str, Any]) -> str:
    payload = task.get("project_memory")
    if not isinstance(payload, dict):
        return ""
    prompt = payload.get("prompt")
    return str(prompt) if isinstance(prompt, str) else ""


def _read_only_required_output_contract(task: dict[str, Any], *, read_only: bool) -> str:
    if not read_only:
        return ""
    profile = str(task.get("read_budget_profile") or "quick_triage").strip().lower()
    budget = task.get("read_budget") if isinstance(task.get("read_budget"), dict) else {}
    max_turns = budget.get("max_worker_turns") or "the configured"
    if profile == "code_contract_audit":
        body = (
            "- suspected_contract: <the data/API contract under review>\n"
            "- producer: <file/function or unknown>\n"
            "- consumer: <file/function or unknown>\n"
            "- mismatch_risk: <none/low/medium/high plus reason>\n"
            "- evidence_files: <1-5 paths already read>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
            "- next_step: <single bounded next action>\n"
        )
    elif profile == "docs_review":
        body = (
            "- audience: <developer/user/operator>\n"
            "- scorecard: <setup/test/usage/architecture status>\n"
            "- gaps: <highest priority gaps>\n"
            "- evidence_files: <1-5 paths already read>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
            "- next_step: <single bounded next action>\n"
        )
    elif profile == "next_task_planning":
        body = (
            "- candidate: <one high-confidence task is enough>\n"
            "- target_files: <likely files>\n"
            "- acceptance_criteria: <how Codex/user verifies it>\n"
            "- risk: <low/medium/high plus reason>\n"
            "- recommended_route: <worker/model/profile>\n"
            "- conclusion: <current answer, partial is acceptable>\n"
        )
    else:
        body = (
            "- conclusion: <current best answer, partial is acceptable>\n"
            "- evidence_files: <1-5 paths already read>\n"
            "- risks: <key risks or unknowns>\n"
            "- next_step: <single bounded next action>\n"
        )
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


def _worker_profile_strategy(task: dict[str, Any]) -> str:
    profile = str(task.get("read_budget_profile") or "").strip().lower()
    if profile == "quick_triage":
        seed_context = _read_only_seed_context(task, profile)
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
        seed_context = _read_only_seed_context(task, profile)
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
    seed_context = _next_task_planning_seed_context(task)
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


def _read_only_seed_context(task: dict[str, Any], profile: str) -> str:
    worktree_raw = task.get("worktree_path") or task.get("repo_path")
    if not worktree_raw:
        return ""
    worktree = Path(str(worktree_raw))
    if not worktree.exists():
        return ""
    files = _read_only_seed_files(worktree, task, profile)
    if not files:
        return ""
    if profile == "code_contract_audit":
        files = files[:16]
        evidence_limit = 8000
        evidence_files = files[:8]
    else:
        files = files[:10]
        evidence_limit = 5000
        evidence_files = files[:5]
    lines = [f"\nSeed files World selected for {profile}; prefer these paths before listing/searching:"]
    for path in files:
        try:
            lines.append(f"- {path.relative_to(worktree).as_posix()}")
        except ValueError:
            continue
    evidence = _seed_evidence(worktree, evidence_files, total_limit=evidence_limit)
    if evidence:
        lines.extend(["", "Seed evidence excerpts; use this before calling Read:", evidence.rstrip()])
    return "\n".join(lines) + "\n"


def _read_only_seed_files(worktree: Path, task: dict[str, Any], profile: str) -> list[Path]:
    roots = _seed_roots_for_profile(profile)
    candidates: list[Path] = []
    explicit_targets = task.get("target_paths")
    if isinstance(explicit_targets, list):
        for target in explicit_targets:
            path = worktree / str(target)
            if path.is_file() and _is_seed_file(path) and _is_seed_file_size_allowed(path):
                candidates.append(path)
    for root in roots:
        path = worktree / root
        if path.is_file() and _is_seed_file(path) and _is_seed_file_size_allowed(path):
            candidates.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and _is_seed_file(child) and _is_seed_file_size_allowed(child):
                    candidates.append(child)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return sorted(unique, key=lambda path: _profile_seed_rank(path, str(task.get("user_goal") or ""), profile))


def _seed_roots_for_profile(profile: str) -> list[str]:
    if profile == "code_contract_audit":
        return ["README.md", "package.json", "js", "server", "tests", "docs"]
    return ["README.md", "package.json", "ARCHITECTURE.md", "js", "server", "docs"]


def _profile_seed_rank(path: Path, goal: str, profile: str) -> tuple[int, int, str]:
    relative = path.as_posix().lower()
    lowered_goal = goal.lower()
    priority = 80
    markers: tuple[str, ...]
    if profile == "code_contract_audit":
        markers = (
            "work-area",
            "workarea",
            "three-work",
            "map-3d",
            "3d",
            "state",
            "route",
            "planner",
            "config",
            "test",
            "spec",
            "readme.md",
            "package.json",
        )
    else:
        markers = (
            "readme.md",
            "package.json",
            "architecture",
            "main",
            "state",
            "map",
            "3d",
            "route",
            "config",
            "test",
        )
    for index, marker in enumerate(markers):
        if marker in relative:
            priority = index
            break
    goal_bonus = 0
    for token in re.findall(r"[A-Za-z0-9_]{3,}", lowered_goal):
        if token in relative:
            goal_bonus -= 2
    if any(marker in lowered_goal for marker in ("workarea", "work area", "选区")) and any(
        marker in relative for marker in ("work-area", "workarea", "three-work", "state")
    ):
        goal_bonus -= 8
    if any(marker in lowered_goal for marker in ("测试", "test", "package")) and any(
        marker in relative for marker in ("package.json", "test", "vitest", "playwright")
    ):
        goal_bonus -= 8
    if any(marker in lowered_goal for marker in ("配置", "config", "projects.yaml")) and any(
        marker in relative for marker in ("package.json", "readme", "config", "architecture")
    ):
        goal_bonus -= 5
    return priority, goal_bonus, relative


def _next_task_planning_seed_context(task: dict[str, Any]) -> str:
    worktree_raw = task.get("worktree_path") or task.get("repo_path")
    if not worktree_raw:
        return ""
    worktree = Path(str(worktree_raw))
    if not worktree.exists():
        return ""
    roots = ["README.md", "js", "server", "tests"]
    files: list[Path] = []
    for root in roots:
        path = worktree / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and _is_seed_file(child) and _is_seed_file_size_allowed(child):
                    files.append(child)
    if not files:
        return ""
    files = sorted(files, key=_seed_file_rank)[:24]
    lines = ["\nSeed files World already selected; prefer these paths and do not list/search the repo:"]
    for path in files:
        try:
            relative = path.relative_to(worktree).as_posix()
        except ValueError:
            continue
        lines.append(f"- {relative}")
    evidence = _seed_evidence(worktree, files[:8], total_limit=7000)
    if evidence:
        lines.extend(
            [
                "",
                "Seed evidence excerpts; use these excerpts before calling Read:",
                evidence.rstrip(),
            ]
        )
    return "\n".join(lines) + "\n"


def _seed_evidence(worktree: Path, files: list[Path], *, total_limit: int) -> str:
    blocks: list[str] = []
    total_chars = 0
    for path in files:
        try:
            if path.stat().st_size > 256_000:
                continue
        except OSError:
            continue
        try:
            relative = path.relative_to(worktree).as_posix()
        except ValueError:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = _seed_file_excerpt(text)
        if not snippet:
            continue
        block = f"### {relative}\n```text\n{snippet}\n```\n"
        if total_chars + len(block) > total_limit:
            break
        blocks.append(block)
        total_chars += len(block)
    return "\n".join(blocks)


def _seed_file_excerpt(text: str, limit: int = 900) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    interesting: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if (
            stripped.startswith(("#", "export ", "function ", "async function ", "class ", "const ", "let "))
            or "todo" in lowered
            or "fixme" in lowered
            or "test(" in lowered
            or "describe(" in lowered
            or "throw new" in lowered
        ):
            interesting.append(stripped)
        if len("\n".join(interesting)) >= limit:
            break
    if not interesting:
        interesting = [line.strip() for line in lines if line.strip()][:20]
    snippet = _redact_seed_excerpt("\n".join(interesting))
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip() + "\n[excerpt truncated]"


_SEED_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s,}]+"),
)


def _redact_seed_excerpt(text: str) -> str:
    redacted = text
    redacted = _SEED_SECRET_PATTERNS[0].sub("[REDACTED_SECRET]", redacted)
    redacted = _SEED_SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def _is_seed_file(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    return path.suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".md", ".html", ".css"}


def _is_seed_file_size_allowed(path: Path) -> bool:
    try:
        return path.stat().st_size <= 256_000
    except OSError:
        return False


def _seed_file_rank(path: Path) -> tuple[int, str]:
    relative = path.as_posix().lower()
    priority = 50
    for index, marker in enumerate(
        (
            "readme.md",
            "package.json",
            "main",
            "route",
            "planner",
            "work-area",
            "map-3d",
            "guide",
            "test",
            "spec",
        )
    ):
        if marker in relative:
            priority = index
            break
    return priority, relative
