from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .runtime_store import RuntimeStore


MEMORY_VERSION = 1
MAX_MEMORY_FILES = 24
MAX_PROMPT_FILES = 10
MAX_FILE_SIZE = 256_000

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s,}]+"),
)


def ensure_project_memory(project_id: str, project: dict[str, Any]) -> dict[str, Any]:
    repo = Path(str(project.get("repo") or "")).expanduser().resolve()
    store = RuntimeStore(repo, str(project.get("world", {}).get("write_policy") or "zero_write"))
    memory_path = store.project_dir / "memory" / "project_memory.json"
    previous = _read_json(memory_path)
    previous_files = {
        item.get("path"): item
        for item in previous.get("files", [])
        if isinstance(item, dict) and item.get("path")
    }

    files: list[dict[str, Any]] = []
    hits = 0
    misses = 0
    skipped = 0
    for path in _candidate_files(repo):
        try:
            stat = path.stat()
        except OSError:
            skipped += 1
            continue
        if stat.st_size > MAX_FILE_SIZE:
            skipped += 1
            continue
        rel = path.relative_to(repo).as_posix()
        content_hash = _file_hash(path)
        cached = previous_files.get(rel)
        if cached and cached.get("content_hash") == content_hash and cached.get("summary"):
            files.append(cached)
            hits += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        files.append(
            {
                "path": rel,
                "content_hash": content_hash,
                "size": stat.st_size,
                "summary": _summarize_file(text),
                "updated_at": _now(),
            }
        )
        misses += 1

    memory = {
        "version": MEMORY_VERSION,
        "project_id": project_id,
        "repo_path": str(repo),
        "stack": list(project.get("stack") or []),
        "test_commands": list(project.get("test_commands") or []),
        "build_commands": list(project.get("build_commands") or []),
        "forbidden_paths": list(project.get("forbidden_paths") or []),
        "files": files,
        "stats": {
            "hit_count": hits,
            "miss_count": misses,
            "skipped_count": skipped,
            "file_count": len(files),
        },
        "updated_at": _now(),
    }
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(memory_path), "memory": memory, "prompt": project_memory_prompt(memory)}


def project_memory_prompt(memory: dict[str, Any]) -> str:
    files = list(memory.get("files") or [])[:MAX_PROMPT_FILES]
    if not files:
        return ""
    stats = memory.get("stats") if isinstance(memory.get("stats"), dict) else {}
    lines = [
        "\n## Project Memory",
        "",
        "Use this cached project memory before reading files. If a referenced file may have changed, prefer checking the file.",
        f"- Project: {memory.get('project_id')}",
        f"- Stack: {', '.join(memory.get('stack') or []) or 'unknown'}",
        f"- Tests: {json.dumps(memory.get('test_commands') or [], ensure_ascii=False)}",
        f"- Memory hits/misses: {stats.get('hit_count', 0)}/{stats.get('miss_count', 0)}",
        "",
        "Cached file summaries:",
    ]
    for item in files:
        lines.append(f"- {item.get('path')}: {item.get('summary')}")
    return "\n".join(lines).rstrip() + "\n"


def _candidate_files(repo: Path) -> list[Path]:
    roots = ["README.md", "pyproject.toml", "package.json", "orchestrator", "console-web/src", "tests", "docs"]
    files: list[Path] = []
    for root in roots:
        path = repo / root
        if path.is_file() and _is_candidate(path):
            files.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and _is_candidate(child):
                    files.append(child)
    return sorted(files, key=_rank_file)[:MAX_MEMORY_FILES]


def _is_candidate(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if any(part in {"__pycache__", ".pytest_cache", ".venv", "node_modules", "dist", "build"} for part in path.parts):
        return False
    return path.suffix.lower() in {".py", ".md", ".toml", ".json", ".ts", ".tsx", ".js", ".css"}


def _rank_file(path: Path) -> tuple[int, str]:
    rel = path.as_posix().lower()
    priority = 50
    for index, marker in enumerate(
        ("readme.md", "pyproject.toml", "scheduler.py", "project_registry.py", "workers", "console", "metrics", "tests")
    ):
        if marker in rel:
            priority = index
            break
    return priority, rel


def _summarize_file(text: str, limit: int = 360) -> str:
    interesting: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if (
            line.startswith(("#", "def ", "class ", "async def ", "from ", "import ", "export ", "type ", "interface "))
            or "pytest" in lowered
            or "test_" in lowered
            or "todo" in lowered
            or any(marker in lowered for marker in ("api_key", "secret", "token", "password", "credential"))
        ):
            interesting.append(line)
        if len(" ".join(interesting)) >= limit:
            break
    if not interesting:
        interesting = [line.strip() for line in text.splitlines() if line.strip()][:8]
    summary = _redact(" ".join(interesting))
    if len(summary) <= limit:
        return summary
    return summary[:limit].rstrip() + "..."


def _redact(text: str) -> str:
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED_SECRET]", text)
    return _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
