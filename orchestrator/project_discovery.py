from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import ScanResult

# Directories to skip during scanning
SKIP_DIRS: set[str] = {
    "node_modules",
    ".git",
    "Library",
    "build",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".eggs",
    "obj",
    "bin",
    "Debug",
    "Release",
    "target",
    ".idea",
    ".vscode",
    ".vs",
    ".gradle",
}

# File patterns to never read contents of
SKIP_FILE_NAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.yaml",
    "secrets.yml",
    "credentials.json",
    "service-account.json",
}

SKIP_FILE_EXTENSIONS: set[str] = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}

# Whitelist: only these files are inspected for content during profiling
WHITELIST_CONFIG_FILES: set[str] = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "pom.xml",
    "Cargo.toml",
    "go.mod",
    "CMakeLists.txt",
    "Makefile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    ".ai-project.yaml",
    "ProjectVersion.txt",
}

MAX_SCAN_DEPTH: int = 5
MAX_SCAN_FILES: int = 10000


def scan_project_roots(
    roots: list[str],
    max_depth: int = MAX_SCAN_DEPTH,
    ignore_list: list[dict[str, str]] | None = None,
) -> ScanResult:
    """Scan root directories to find project candidates (paths containing .git)."""
    candidates: list[Path] = []
    skipped: list[Path] = []
    roots_scanned: list[str] = []

    ignore_patterns = _build_ignore_patterns(ignore_list or [])

    for root_str in roots:
        root = Path(root_str).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            continue
        roots_scanned.append(str(root))

        for candidate in _walk_for_git(root, max_depth, ignore_patterns):
            if candidate in candidates:
                continue
            if _should_skip(candidate, ignore_patterns):
                skipped.append(candidate)
                continue
            candidates.append(candidate)

    return ScanResult(
        candidates=candidates,
        skipped=skipped,
        roots_scanned=roots_scanned,
    )


def find_git_root(start: Path) -> Path | None:
    """Walk upward from start to find the nearest .git directory parent."""
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def is_git_repo(path: Path) -> bool:
    """Check if path is the root of a git repository."""
    return (path / ".git").exists() and (path / ".git").is_dir()


def is_safe_to_read(filepath: Path) -> bool:
    """Check if a file is safe to read (not a secret/config with sensitive data)."""
    name = filepath.name.lower()
    if name in SKIP_FILE_NAMES:
        return False
    if any(name.endswith(ext) for ext in SKIP_FILE_EXTENSIONS):
        return False
    return True


def is_whitelisted_config(filepath: Path) -> bool:
    """Check if a file is a known project configuration file."""
    return filepath.name in WHITELIST_CONFIG_FILES or filepath.suffix == ".yaml" and "config" in filepath.name.lower()


def _walk_for_git(
    root: Path,
    max_depth: int,
    ignore_patterns: list[dict[str, Any]],
    _depth: int = 0,
    _file_count: list[int] | None = None,
) -> list[Path]:
    """Walk directory tree looking for .git directories. Returns list of repo roots."""
    if _file_count is None:
        _file_count = [0]
    results: list[Path] = []

    if _depth > max_depth or _file_count[0] > MAX_SCAN_FILES:
        return results

    # Check if root itself is a git repo
    if is_git_repo(root):
        return [root]

    try:
        for entry in root.iterdir():
            if _file_count[0] > MAX_SCAN_FILES:
                break
            _file_count[0] += 1

            if not entry.is_dir():
                continue
            if entry.name in SKIP_DIRS or (entry.name.startswith(".") and entry.name != ".git"):
                continue

            if is_git_repo(entry):
                results.append(entry)
            elif _depth < max_depth:
                results.extend(_walk_for_git(entry, max_depth, ignore_patterns, _depth + 1, _file_count))
    except PermissionError:
        pass

    return results


def _build_ignore_patterns(ignore_list: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Normalize ignore list entries into pattern dicts."""
    patterns: list[dict[str, Any]] = []
    for entry in ignore_list:
        if isinstance(entry, dict):
            patterns.append({
                "pattern": entry.get("pattern", entry.get("path", "")),
                "reason": entry.get("reason", ""),
            })
        elif isinstance(entry, str):
            patterns.append({"pattern": entry, "reason": ""})
    return patterns


def _should_skip(path: Path, ignore_patterns: list[dict[str, Any]]) -> bool:
    """Check if a path matches any ignore pattern."""
    path_str = str(path).replace("\\", "/")
    for ip in ignore_patterns:
        pattern = ip["pattern"].replace("\\", "/")
        if _match_glob(path_str, pattern):
            return True
    return False


def _match_glob(path_str: str, pattern: str) -> bool:
    """Simple glob matching. Supports * and **, and suffix matching."""
    import fnmatch

    # Direct fnmatch on full path
    if fnmatch.fnmatch(path_str, pattern):
        return True
    # fnmatch on just the name
    name = path_str.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(name, pattern):
        return True
    # Try matching any parent directory
    parts = path_str.split("/")
    for i in range(len(parts)):
        partial = "/".join(parts[: i + 1])
        if fnmatch.fnmatch(partial, pattern):
            return True
    # Suffix match: pattern like "*/skipped-dir" should match path ending with "/skipped-dir"
    if pattern.startswith("*/"):
        suffix = pattern[1:]  # "/skipped-dir"
        if path_str.endswith(suffix) or path_str.endswith(suffix.replace("/", "\\")):
            return True
    return False
