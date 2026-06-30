from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def read_only_seed_context(task: dict[str, Any], profile: str) -> str:
    worktree = _task_worktree(task)
    if worktree is None:
        return ""
    files = read_only_seed_files(worktree, task, profile)
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
    evidence = seed_evidence(worktree, evidence_files, total_limit=evidence_limit)
    if evidence:
        lines.extend(["", "Seed evidence excerpts; use this before calling Read:", evidence.rstrip()])
    return "\n".join(lines) + "\n"


def next_task_planning_seed_context(task: dict[str, Any]) -> str:
    worktree = _task_worktree(task)
    if worktree is None:
        return ""
    files: list[Path] = []
    for root in ["README.md", "js", "server", "tests"]:
        path = worktree / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and is_seed_file(child) and is_seed_file_size_allowed(child):
                    files.append(child)
    if not files:
        return ""
    files = sorted(files, key=seed_file_rank)[:24]
    lines = ["\nSeed files World already selected; prefer these paths and do not list/search the repo:"]
    for path in files:
        try:
            relative = path.relative_to(worktree).as_posix()
        except ValueError:
            continue
        lines.append(f"- {relative}")
    evidence = seed_evidence(worktree, files[:8], total_limit=7000)
    if evidence:
        lines.extend(
            [
                "",
                "Seed evidence excerpts; use these excerpts before calling Read:",
                evidence.rstrip(),
            ]
        )
    return "\n".join(lines) + "\n"


def read_only_seed_files(worktree: Path, task: dict[str, Any], profile: str) -> list[Path]:
    roots = seed_roots_for_profile(profile)
    candidates: list[Path] = []
    explicit_targets = task.get("target_paths")
    if isinstance(explicit_targets, list):
        for target in explicit_targets:
            path = worktree / str(target)
            if path.is_file() and is_seed_file(path) and is_seed_file_size_allowed(path):
                candidates.append(path)
    for root in roots:
        path = worktree / root
        if path.is_file() and is_seed_file(path) and is_seed_file_size_allowed(path):
            candidates.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and is_seed_file(child) and is_seed_file_size_allowed(child):
                    candidates.append(child)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return sorted(unique, key=lambda path: profile_seed_rank(path, str(task.get("user_goal") or ""), profile))


def seed_roots_for_profile(profile: str) -> list[str]:
    if profile == "code_contract_audit":
        return ["README.md", "package.json", "js", "server", "tests", "docs"]
    return ["README.md", "package.json", "ARCHITECTURE.md", "js", "server", "docs"]


def profile_seed_rank(path: Path, goal: str, profile: str) -> tuple[int, int, str]:
    relative = path.as_posix().lower()
    lowered_goal = goal.lower()
    priority = 80
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


def seed_evidence(worktree: Path, files: list[Path], *, total_limit: int) -> str:
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
        snippet = seed_file_excerpt(text)
        if not snippet:
            continue
        block = f"### {relative}\n```text\n{snippet}\n```\n"
        if total_chars + len(block) > total_limit:
            break
        blocks.append(block)
        total_chars += len(block)
    return "\n".join(blocks)


def seed_file_excerpt(text: str, limit: int = 900) -> str:
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
    snippet = redact_seed_excerpt("\n".join(interesting))
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip() + "\n[excerpt truncated]"


SEED_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s,}]+"),
)


def redact_seed_excerpt(text: str) -> str:
    redacted = text
    redacted = SEED_SECRET_PATTERNS[0].sub("[REDACTED_SECRET]", redacted)
    redacted = SEED_SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def is_seed_file(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    return path.suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".md", ".html", ".css"}


def is_seed_file_size_allowed(path: Path) -> bool:
    try:
        return path.stat().st_size <= 256_000
    except OSError:
        return False


def seed_file_rank(path: Path) -> tuple[int, str]:
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


def _task_worktree(task: dict[str, Any]) -> Path | None:
    worktree_raw = task.get("worktree_path") or task.get("repo_path")
    if not worktree_raw:
        return None
    worktree = Path(str(worktree_raw))
    return worktree if worktree.exists() else None
