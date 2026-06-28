from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import ProjectIndicator, ProjectProfile

# ── Indicator definitions ──

INDICATOR_DEFS: list[dict[str, Any]] = [
    # path, project_type, weight, match_type
    {"path": ".git", "project_type": "git_root", "weight": 1.0, "match_type": "directory"},
    {"path": "package.json", "project_type": "node", "weight": 0.7, "match_type": "file"},
    {"path": "pyproject.toml", "project_type": "python", "weight": 0.7, "match_type": "file"},
    {"path": "requirements.txt", "project_type": "python", "weight": 0.5, "match_type": "file"},
    {"path": "build.gradle", "project_type": "java", "weight": 0.6, "match_type": "file"},
    {"path": "build.gradle.kts", "project_type": "java", "weight": 0.6, "match_type": "file"},
    {"path": "settings.gradle", "project_type": "java", "weight": 0.6, "match_type": "file"},
    {"path": "settings.gradle.kts", "project_type": "java", "weight": 0.6, "match_type": "file"},
    {"path": "android/app/build.gradle", "project_type": "android", "weight": 0.9, "match_type": "nested"},
    {"path": "android/app/build.gradle.kts", "project_type": "android", "weight": 0.9, "match_type": "nested"},
    {"path": "ProjectSettings/ProjectVersion.txt", "project_type": "unity", "weight": 0.9, "match_type": "nested"},
    {"path": "pom.xml", "project_type": "maven", "weight": 0.8, "match_type": "file"},
    {"path": "docker-compose.yml", "project_type": "docker", "weight": 0.6, "match_type": "file"},
    {"path": "docker-compose.yaml", "project_type": "docker", "weight": 0.6, "match_type": "file"},
]

# Glob-based indicators (checked with Path.glob)
GLOB_INDICATORS: list[dict[str, Any]] = [
    {"glob": "vite.config.*", "project_type": "vite", "weight": 0.8},
    {"glob": "next.config.*", "project_type": "next", "weight": 0.8},
    {"glob": "next.config.js", "project_type": "next", "weight": 0.8},
    {"glob": "next.config.mjs", "project_type": "next", "weight": 0.8},
    {"glob": "next.config.ts", "project_type": "next", "weight": 0.8},
]

# Sub-type content detection
SUBTYPE_PATTERNS: list[dict[str, Any]] = [
    # (file, regex pattern, stack_label)
    {"file": "pyproject.toml", "pattern": r"fastapi", "label": "fastapi"},
    {"file": "pyproject.toml", "pattern": r"django", "label": "django"},
    {"file": "pyproject.toml", "pattern": r"flask", "label": "flask"},
    {"file": "pyproject.toml", "pattern": r"pytest", "label": "pytest"},
    {"file": "requirements.txt", "pattern": r"fastapi", "label": "fastapi"},
    {"file": "requirements.txt", "pattern": r"django", "label": "django"},
    {"file": "requirements.txt", "pattern": r"flask", "label": "flask"},
    {"file": "package.json", "pattern": r'"next"\s*:', "label": "next"},
    {"file": "package.json", "pattern": r'"react"\s*:', "label": "react"},
    {"file": "package.json", "pattern": r'"vue"\s*:', "label": "vue"},
    {"file": "package.json", "pattern": r'"vite"\s*:', "label": "vite"},
    {"file": "package.json", "pattern": r'"express"\s*:', "label": "express"},
    {"file": "package.json", "pattern": r'"typescript"\s*:', "label": "typescript"},
    {"file": "package.json", "pattern": r'"tailwindcss"\s*:', "label": "tailwind"},
    {"file": "build.gradle", "pattern": r"android", "label": "android"},
    {"file": "build.gradle.kts", "pattern": r"android", "label": "android"},
]

# Conflict resolution: mutually exclusive types
TYPE_CONFLICTS: dict[str, set[str]] = {
    "android": {"java"},
    "node": {"python", "maven", "java"},
    "python": {"node", "maven", "java"},
    "maven": {"node", "python"},
    "unity": {"node", "python", "java", "maven"},
    "vite": {"maven", "java", "python"},
    "next": {"maven", "java", "python"},
}


def profile_project(repo_path: str | Path) -> ProjectProfile:
    """Analyze a project directory and return a full ProjectProfile."""
    repo = Path(repo_path).expanduser().resolve()

    # Collect all indicators
    indicators = _collect_indicators(repo)

    # Determine primary type and confidence
    project_type, confidence = _compute_type_and_confidence(indicators)

    # Detect subtypes / stack labels
    stack = _detect_subtypes(repo, project_type, indicators)

    # Generate project_id from directory name
    name = repo.name
    project_id = name.lower().replace(" ", "-").replace("_", "-")

    return ProjectProfile(
        project_id=project_id,
        name=name,
        repo=str(repo),
        project_type=project_type,
        stack=list(dict.fromkeys(stack)),  # dedupe preserving order
        confidence=confidence,
        status="pending_confirmation" if confidence < 0.75 else "active",
        auto_generated=True,
        indicators=[_indicator_to_dict(ind) for ind in indicators],
    )


def _collect_indicators(repo: Path) -> list[ProjectIndicator]:
    """Collect all detection signals from a repo directory.

    Searches repo root first, then subdirectories up to 2 levels deep
    to support monorepo layouts (e.g., apps/backend/pyproject.toml).
    """
    indicators: list[ProjectIndicator] = []

    # Files/dirs to skip when searching subdirectories
    _skip_names = {"node_modules", ".git", "Library", "build", "dist", "__pycache__",
                   ".venv", "venv", ".tox", ".eggs", "obj", "bin", ".idea", ".vscode",
                   ".gradle", "target", ".pytest_cache", "uploads", "data"}

    # Collect candidate directories: root + up to 2 levels of subdirs
    candidate_dirs = [repo]
    try:
        for entry in sorted(repo.iterdir()):
            if entry.is_dir() and entry.name not in _skip_names and not entry.name.startswith("."):
                candidate_dirs.append(entry)
                # One level deeper
                try:
                    for sub in sorted(entry.iterdir()):
                        if sub.is_dir() and sub.name not in _skip_names and not sub.name.startswith("."):
                            candidate_dirs.append(sub)
                except PermissionError:
                    pass
    except PermissionError:
        pass

    # Search each candidate directory for indicators
    for search_dir in candidate_dirs:
        for defn in INDICATOR_DEFS:
            target = search_dir / defn["path"]
            if defn["match_type"] == "directory":
                if target.is_dir():
                    indicators.append(ProjectIndicator(
                        name=defn["path"],
                        path=str(target.relative_to(repo)).replace("\\", "/"),
                        project_type=defn["project_type"],
                        weight=defn["weight"],
                        matched_by="directory",
                    ))
            elif defn["match_type"] in ("file", "nested"):
                if target.is_file():
                    indicators.append(ProjectIndicator(
                        name=defn["path"],
                        path=str(target.relative_to(repo)).replace("\\", "/"),
                        project_type=defn["project_type"],
                        weight=defn["weight"],
                        matched_by=defn["match_type"],
                    ))

    # Glob-based indicators (already match in subdirs)
    for defn in GLOB_INDICATORS:
        matches = list(repo.glob(defn["glob"]))
        if matches:
            for match in matches:
                indicators.append(ProjectIndicator(
                    name=match.name,
                    path=str(match.relative_to(repo)).replace("\\", "/"),
                    project_type=defn["project_type"],
                    weight=defn["weight"],
                    matched_by="glob",
                ))

    # Deduplicate by (name, project_type)
    seen = set()
    unique: list[ProjectIndicator] = []
    for ind in indicators:
        key = (ind.name, ind.project_type)
        if key not in seen:
            seen.add(key)
            unique.append(ind)

    return unique


def _compute_type_and_confidence(indicators: list[ProjectIndicator]) -> tuple[str, float]:
    """Compute project type and confidence from collected indicators."""
    # Separate git_root from project indicators
    has_git = any(ind.project_type == "git_root" for ind in indicators)
    project_indicators = [ind for ind in indicators if ind.project_type != "git_root"]

    if not project_indicators:
        if has_git:
            return "unknown", 0.3
        return "unknown", 0.0

    # Group by project_type, collect weights
    type_weights: dict[str, list[float]] = {}
    for ind in project_indicators:
        if ind.project_type not in type_weights:
            type_weights[ind.project_type] = []
        type_weights[ind.project_type].append(ind.weight)

    # Find primary type (highest max weight)
    type_max_weights = {t: max(ws) for t, ws in type_weights.items()}
    primary_type = max(type_max_weights, key=lambda t: type_max_weights[t])
    max_weight = type_max_weights[primary_type]

    # Count non-conflicting extra indicators
    conflict_set = TYPE_CONFLICTS.get(primary_type, set())
    extra_count = 0
    for ind in project_indicators:
        if ind.project_type != primary_type and ind.project_type not in conflict_set:
            extra_count += 1

    # Compute confidence
    if len(project_indicators) == 1:
        confidence = max_weight
    elif extra_count > 0 and not _has_conflict(project_indicators, primary_type):
        confidence = min(1.0, max_weight + 0.1 * extra_count)
    elif _has_conflict(project_indicators, primary_type):
        confidence = max_weight - 0.05
    else:
        confidence = max_weight

    # Git bonus: having a git repo is a meaningful signal
    if has_git and project_indicators:
        confidence += 0.05

    # Cap and clamp
    confidence = max(0.0, min(1.0, confidence))

    # Special case: android/app/build.gradle gives android directly
    has_android_nested = any(
        ind.project_type == "android" and ind.matched_by == "nested"
        for ind in project_indicators
    )
    if has_android_nested:
        primary_type = "android"
        confidence = max(confidence, 0.9)

    return primary_type, round(confidence, 2)


def _has_conflict(indicators: list[ProjectIndicator], primary_type: str) -> bool:
    """Check if indicators contain conflicting type signals."""
    conflict_set = TYPE_CONFLICTS.get(primary_type, set())
    for ind in indicators:
        if ind.project_type in conflict_set:
            return True
    return False


def _detect_subtypes(
    repo: Path,
    project_type: str,
    indicators: list[ProjectIndicator] | None = None,
) -> list[str]:
    """Detect sub-stack labels by inspecting config file content.

    Also includes all non-conflicting types from indicators
    to support multi-stack projects (e.g., Android + Python + Docker).
    """
    stack: list[str] = []

    # Always include the primary type
    if project_type and project_type not in ("unknown", "git_root"):
        stack.append(project_type)

    # Include other detected types from indicators (multi-stack support)
    if indicators:
        conflict_set = TYPE_CONFLICTS.get(project_type, set())
        for ind in indicators:
            if ind.project_type == "git_root":
                continue
            if ind.project_type != project_type and ind.project_type not in conflict_set:
                if ind.project_type not in stack:
                    stack.append(ind.project_type)

    for defn in SUBTYPE_PATTERNS:
        target = repo / defn["file"]
        if not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            if re.search(defn["pattern"], content, re.IGNORECASE):
                label = defn["label"]
                if label not in stack:
                    stack.append(label)
        except (OSError, UnicodeDecodeError):
            continue

    return stack


def _indicator_to_dict(ind: ProjectIndicator) -> dict[str, Any]:
    """Convert a ProjectIndicator to a plain dict."""
    return {
        "name": ind.name,
        "path": ind.path,
        "project_type": ind.project_type,
        "weight": ind.weight,
        "matched_by": ind.matched_by,
    }


def read_ai_project_yaml(repo_path: str | Path) -> dict[str, Any] | None:
    """Read .ai-project.yaml from a project directory if it exists."""
    repo = Path(repo_path).expanduser().resolve()
    marker = repo / ".ai-project.yaml"
    if not marker.exists():
        return None
    import yaml  # lazy to match codebase pattern

    try:
        with marker.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception:
        return None
