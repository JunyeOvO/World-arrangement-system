from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .types import ProjectFingerprint

# Directories to exclude from file tree
EXCLUDE_DIRS: set[str] = {
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
    ".gradle",
    "logs",
    "tmp",
    "temp",
}

# Files that contribute to fingerprint hash
KEY_CONFIG_FILES: set[str] = {
    "pyproject.toml",
    "package.json",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "pom.xml",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "yarn.lock",
    "package-lock.json",
    "Makefile",
    "CMakeLists.txt",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    ".ai-project.yaml",
    "ProjectVersion.txt",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mts",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
}

MAX_FILES = 5000


def compute_fingerprint(repo: str | Path, project_id: str = "") -> ProjectFingerprint:
    """Compute a structural fingerprint for a project repository."""
    repo_path = Path(repo).expanduser().resolve()

    file_tree = _build_file_tree(repo_path)
    key_files = _hash_key_files(repo_path)

    # Compute composite hash
    hasher = hashlib.sha256()
    hasher.update("\n".join(sorted(file_tree)).encode("utf-8"))
    hasher.update(json.dumps(key_files, sort_keys=True).encode("utf-8"))
    fingerprint_hash = hasher.hexdigest()

    return ProjectFingerprint(
        project_id=project_id or repo_path.name,
        hash=fingerprint_hash,
        file_tree=file_tree,
        key_files=key_files,
    )


def has_changed(old_fingerprint: str, new_fingerprint: str) -> bool:
    """Check if fingerprints differ."""
    return old_fingerprint != new_fingerprint


def _build_file_tree(repo_path: Path) -> list[str]:
    """Build a sorted list of relative file paths, excluding noise directories."""
    paths: list[str] = []
    file_count = 0

    for entry in repo_path.rglob("*"):
        if file_count >= MAX_FILES:
            break

        # Skip excluded directories
        if _is_excluded(entry, repo_path):
            continue

        if entry.is_file():
            try:
                rel = entry.relative_to(repo_path)
                paths.append(str(rel).replace("\\", "/"))
            except ValueError:
                continue
            file_count += 1

    paths.sort()
    return paths


def _hash_key_files(repo_path: Path) -> dict[str, str]:
    """Compute SHA256 hashes for key configuration files.

    Searches at root and in subdirectories up to 2 levels
    to support monorepo layouts.
    """
    hashes: dict[str, str] = {}

    # Build candidate directories
    _skip = {"node_modules", ".git", "build", "dist", "__pycache__",
             ".venv", "venv", ".idea", ".vscode", ".gradle", ".pytest_cache"}
    dirs = [repo_path]
    try:
        for entry in sorted(repo_path.iterdir()):
            if entry.is_dir() and entry.name not in _skip and not entry.name.startswith("."):
                dirs.append(entry)
                try:
                    for sub in sorted(entry.iterdir()):
                        if sub.is_dir() and sub.name not in _skip and not sub.name.startswith("."):
                            dirs.append(sub)
                except PermissionError:
                    pass
    except PermissionError:
        pass

    for search_dir in dirs:
        for key_file in KEY_CONFIG_FILES:
            target = search_dir / key_file
            if target.is_file():
                try:
                    rel = target.relative_to(repo_path)
                    content = target.read_bytes()
                    h = hashlib.sha256(content).hexdigest()
                    hashes[str(rel).replace("\\", "/")] = h
                except (OSError, PermissionError, ValueError):
                    continue

    return hashes


def _is_excluded(entry: Path, root: Path) -> bool:
    """Check if a path entry should be excluded from fingerprinting."""
    # Check each part of the relative path for excluded dirs
    try:
        rel = entry.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True
        if part.startswith(".") and part != ".ai-project.yaml":
            return True
    return False
