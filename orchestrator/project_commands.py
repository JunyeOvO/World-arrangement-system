from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_adaptation import batch_refresh, refresh_project_profile
from .project_discovery import scan_project_roots as _scan_roots
from .project_fingerprint import compute_fingerprint
from .project_profiler import profile_project, read_ai_project_yaml
from .project_registry import (
    confirm_project,
    get_ignore_list,
    ignore_project_in_registry,
    list_pending_projects,
    load_full_registry,
    load_projects,
    register_project_to_yaml,
)

DEFAULT_SCAN_ROOTS = [
    str(Path.home() / "dev"),
    str(Path.home() / "projects"),
    str(Path.home() / "Documents"),
]


def handle_scan_project_roots(
    roots: list[str] | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Scan root directories for project candidates (.git repos)."""
    if not roots:
        roots = [r for r in DEFAULT_SCAN_ROOTS if Path(r).expanduser().exists()]
        if not roots:
            roots = [str(Path.home())]

    ignore_list = get_ignore_list()
    result = _scan_roots(roots, max_depth=max_depth, ignore_list=ignore_list)

    return {
        "candidates": [str(c) for c in result.candidates],
        "skipped": [str(s) for s in result.skipped],
        "roots_scanned": result.roots_scanned,
        "total_candidates": len(result.candidates),
    }


def handle_discover_projects(
    roots: list[str] | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Scan + profile: discover projects in roots and return full profiles."""
    scan_result = handle_scan_project_roots(roots, max_depth)
    candidates = scan_result.get("candidates", [])

    profiles: list[dict[str, Any]] = []
    for cand_path in candidates:
        try:
            profile = profile_project(cand_path)
            # Compute fingerprint
            fp = compute_fingerprint(cand_path, profile.project_id)
            profile.fingerprint = fp.hash
            profiles.append(_profile_to_summary(profile))
        except Exception as exc:
            profiles.append({
                "repo": cand_path,
                "error": str(exc),
            })

    # Categorize
    high_conf = [p for p in profiles if p.get("confidence", 0) >= 0.75 and "error" not in p]
    low_conf = [p for p in profiles if p.get("confidence", 0) < 0.75 and "error" not in p]
    errors = [p for p in profiles if "error" in p]

    return {
        "total_discovered": len(profiles),
        "high_confidence": high_conf,
        "low_confidence": low_conf,
        "errors": errors,
        "roots_scanned": scan_result.get("roots_scanned", []),
    }


def handle_profile_project(repo_path: str, force: bool = False) -> dict[str, Any]:
    """Deep-profile a single project."""
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        return {"status": "error", "message": f"path does not exist: {repo}"}

    profile = profile_project(repo)
    fp = compute_fingerprint(repo, profile.project_id)
    profile.fingerprint = fp.hash

    # Check ai-project.yaml for overrides
    ai_config = read_ai_project_yaml(repo)
    if ai_config:
        if ai_config.get("project_id"):
            profile.project_id = ai_config["project_id"]
        if ai_config.get("name"):
            profile.name = ai_config["name"]
        if ai_config.get("project_type"):
            profile.project_type = ai_config["project_type"]
        if ai_config.get("stack"):
            profile.stack = ai_config["stack"]
        if ai_config.get("project_group"):
            profile.project_group = ai_config["project_group"]
        # If user manually created .ai-project.yaml, it's user-managed
        if not ai_config.get("auto_generated", True):
            profile.auto_generated = False

    return _profile_to_summary(profile)


def handle_register_project(repo_path: str, confirm: bool = False) -> dict[str, Any]:
    """Register a discovered project into projects.yaml."""
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        return {"status": "error", "message": f"path does not exist: {repo}"}

    profile = profile_project(repo)
    fp = compute_fingerprint(repo, profile.project_id)
    profile.fingerprint = fp.hash

    # Check for .ai-project.yaml overrides
    ai_config = read_ai_project_yaml(repo)
    if ai_config and ai_config.get("project_id"):
        profile.project_id = ai_config["project_id"]

    # Check if already registered
    existing = load_projects().get(profile.project_id)
    if existing and not confirm:
        return {
            "status": "already_registered",
            "project_id": profile.project_id,
            "existing": {k: v for k, v in existing.items() if k in ("name", "project_type", "confidence", "status", "auto_generated")},
        }

    result = register_project_to_yaml(profile, force=confirm)
    result["profile"] = _profile_to_summary(profile)
    return result


def handle_refresh_project_profile(project_id: str) -> dict[str, Any]:
    """Refresh a registered project's profile."""
    return refresh_project_profile(project_id)


def handle_list_unregistered_projects() -> dict[str, Any]:
    """List projects in pending_confirmation status."""
    pending = list_pending_projects()
    return {
        "pending": pending,
        "count": len(pending),
    }


def handle_confirm_project_profile(project_id: str) -> dict[str, Any]:
    """Confirm a pending project."""
    return confirm_project(project_id)


def handle_ignore_project(repo_path: str, reason: str = "") -> dict[str, Any]:
    """Add a project path to the ignore list."""
    return ignore_project_in_registry(repo_path, reason)


def handle_batch_discover_and_register(
    roots: list[str] | None = None,
    max_depth: int = 3,
    auto_register: bool = False,
) -> dict[str, Any]:
    """Full pipeline: scan → profile → register (optional)."""
    scan_result = handle_scan_project_roots(roots, max_depth)
    candidates = scan_result.get("candidates", [])

    registered: list[str] = []
    pending: list[str] = []
    skipped: list[str] = []

    for cand_path in candidates:
        try:
            profile = profile_project(cand_path)
            fp = compute_fingerprint(cand_path, profile.project_id)
            profile.fingerprint = fp.hash

            if auto_register:
                result = register_project_to_yaml(profile)
                if result["status"] == "registered":
                    registered.append(profile.project_id)
                elif result["status"] == "pending_confirmation":
                    pending.append(profile.project_id)
            else:
                # Just profile without registering
                if profile.confidence >= 0.75:
                    registered.append(profile.project_id)
                else:
                    pending.append(profile.project_id)
        except Exception:
            skipped.append(cand_path)

    return {
        "total_candidates": len(candidates),
        "registered": registered,
        "pending_confirmation": pending,
        "skipped": skipped,
        "roots_scanned": scan_result.get("roots_scanned", []),
    }


def _profile_to_summary(profile: Any) -> dict[str, Any]:
    """Convert a ProjectProfile to a summary dict for tool responses."""
    return {
        "project_id": profile.project_id,
        "name": profile.name,
        "repo": profile.repo,
        "project_type": profile.project_type,
        "stack": profile.stack,
        "confidence": profile.confidence,
        "status": profile.status,
        "auto_generated": profile.auto_generated,
        "indicators": profile.indicators,
        "fingerprint": getattr(profile, "fingerprint", ""),
        "needs_refresh": profile.needs_refresh,
        "first_seen": profile.first_seen,
        "last_seen": profile.last_seen,
        "project_group": profile.project_group,
        "metadata": profile.metadata,
    }
