"""Static Worker Permission Enforcer — Phase 5 upgrade.

Loads config/worker_permissions.yaml and enforces static permission profiles.
Two immutable profiles: standard_safe (ClaudeCodeWorker) and advanced_code_safe (OpenCodeWorker).

Design principle: Ability ≠ Permission.
OpenCodeWorker has a stronger model but the same danger boundaries.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PermissionCheck:
    """Result of a single permission check."""

    allowed: bool
    reason: str = ""
    requires_ask: bool = False
    matched_pattern: str = ""
    action: str = ""
    target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "requires_ask": self.requires_ask,
            "matched_pattern": self.matched_pattern,
            "action": self.action,
            "target": self.target,
        }


@dataclass
class PermissionReview:
    worker: str
    allowed: bool = True
    requires_ask: bool = False
    checks: list[PermissionCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker": self.worker,
            "allowed": self.allowed,
            "requires_ask": self.requires_ask,
            "checks": [check.to_dict() for check in self.checks],
            "denied": [check.to_dict() for check in self.checks if not check.allowed],
            "ask": [check.to_dict() for check in self.checks if check.requires_ask],
        }


@dataclass
class WorkerPermissions:
    """Static permission profile for a worker."""

    profile: str
    read_allow: list[str] = field(default_factory=list)
    read_deny: list[str] = field(default_factory=list)
    write_allow: list[str] = field(default_factory=list)
    write_ask: list[str] = field(default_factory=list)
    write_deny: list[str] = field(default_factory=list)
    bash_allow: list[str] = field(default_factory=list)
    bash_ask: list[str] = field(default_factory=list)
    bash_deny: list[str] = field(default_factory=list)
    provider_allow: list[str] = field(default_factory=list)
    provider_deny: list[str] = field(default_factory=list)
    model_default: str = ""
    effort_default: str = "medium"
    timeout_sec: int = 300


_PERMISSIONS_CACHE: dict[str, WorkerPermissions] = {}


def load_permissions(worker_name: str) -> WorkerPermissions:
    """Load the static permission profile for a worker.

    Reads config/worker_permissions.yaml and caches the result.
    """
    if worker_name in _PERMISSIONS_CACHE:
        return _PERMISSIONS_CACHE[worker_name]

    config_path = Path(__file__).resolve().parents[1] / "config" / "worker_permissions.yaml"
    if not config_path.exists():
        return _default_permissions(worker_name)

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return _default_permissions(worker_name)

    workers_data = data.get("workers", {})
    worker_data = workers_data.get(worker_name, {})

    perms = worker_data.get("permissions", {})
    read_cfg = perms.get("read", {})
    write_cfg = perms.get("write", {})
    bash_cfg = perms.get("bash", {})

    wp = WorkerPermissions(
        profile=worker_data.get("profile", "unknown"),
        read_allow=read_cfg.get("allow", ["**/*"]),
        read_deny=read_cfg.get("deny", []),
        write_allow=write_cfg.get("allow", []),
        write_ask=write_cfg.get("ask", []),
        write_deny=write_cfg.get("deny", []),
        bash_allow=bash_cfg.get("allow", []),
        bash_ask=bash_cfg.get("ask", []),
        bash_deny=bash_cfg.get("deny", []),
        provider_allow=worker_data.get("provider_allow", []),
        provider_deny=worker_data.get("provider_deny", []),
        model_default=worker_data.get("model_default", ""),
        effort_default=worker_data.get("effort_default", "medium"),
        timeout_sec=worker_data.get("timeout_sec", 300),
    )
    _PERMISSIONS_CACHE[worker_name] = wp
    return wp


def check_write_path(worker_name: str, file_path: str) -> PermissionCheck:
    """Check if a worker is allowed to write to a file path."""
    wp = load_permissions(worker_name)

    # Deny takes priority
    for pattern in wp.write_deny:
        if _path_matches(file_path, pattern):
            return PermissionCheck(False, f"write denied by pattern: {pattern}", False, pattern, "write", file_path)

    # Ask (dependency/config files)
    for pattern in wp.write_ask:
        if _path_matches(file_path, pattern):
            return PermissionCheck(True, f"write requires ask for: {pattern}", True, pattern, "write", file_path)

    # Explicit allow
    for pattern in wp.write_allow:
        if _path_matches(file_path, pattern):
            return PermissionCheck(True, f"write allowed by pattern: {pattern}", False, pattern, "write", file_path)

    # Default deny (not in any allow list)
    return PermissionCheck(False, f"write path not in allow list: {file_path}", False, "", "write", file_path)


def check_write_paths(worker_name: str, file_paths: list[str]) -> PermissionReview:
    review = PermissionReview(worker=worker_name)
    for file_path in file_paths:
        check = check_write_path(worker_name, file_path)
        review.checks.append(check)
        if not check.allowed:
            review.allowed = False
        if check.requires_ask:
            review.requires_ask = True
    return review


def check_bash_command(worker_name: str, command: str) -> PermissionCheck:
    """Check if a worker is allowed to run a bash command."""
    wp = load_permissions(worker_name)
    normalized = command.strip()

    # Deny takes priority
    for pattern in wp.bash_deny:
        if _command_matches(normalized, pattern):
            return PermissionCheck(False, f"bash denied by pattern: {pattern}", False, pattern, "bash", command)

    # Ask
    for pattern in wp.bash_ask:
        if _command_matches(normalized, pattern):
            return PermissionCheck(True, f"bash requires ask for: {pattern}", True, pattern, "bash", command)

    # Explicit allow
    for pattern in wp.bash_allow:
        if _command_matches(normalized, pattern):
            return PermissionCheck(True, f"bash allowed by pattern: {pattern}", False, pattern, "bash", command)

    # Default deny
    return PermissionCheck(False, f"bash command not in allow list: {command[:80]}", False, "", "bash", command)


def check_worker_launch_command(worker_name: str, command: str) -> PermissionCheck:
    """Guard the actual worker CLI command against static deny rules.

    Worker launch commands are not generic project bash commands, so they do not
    need to match bash.allow. They must, however, never contain a denied bypass
    or destructive command pattern.
    """
    wp = load_permissions(worker_name)
    for pattern in wp.bash_deny:
        if _command_matches(command.strip(), pattern):
            return PermissionCheck(False, f"worker command denied by pattern: {pattern}", False, pattern, "worker_command", command)
    return PermissionCheck(True, "worker command passed deny-list check", False, "", "worker_command", command)


def check_provider(worker_name: str, provider: str) -> PermissionCheck:
    """Check if a worker is allowed to use a model provider."""
    wp = load_permissions(worker_name)
    provider_lower = provider.lower()

    for deny in wp.provider_deny:
        if deny.lower() in provider_lower:
            return PermissionCheck(False, f"provider denied: {deny}", False, deny, "provider", provider)

    for allow in wp.provider_allow:
        if allow.lower() in provider_lower:
            return PermissionCheck(True, f"provider allowed: {allow}", False, allow, "provider", provider)

    if not wp.provider_allow:
        return PermissionCheck(True, "no provider restrictions", False, "", "provider", provider)

    return PermissionCheck(False, f"provider not in allow list: {provider}", False, "", "provider", provider)


def _path_matches(file_path: str, pattern: str) -> bool:
    """Check if a file path matches a glob pattern."""
    normalized = file_path.replace("\\", "/")
    pattern_norm = pattern.replace("\\", "/")
    return fnmatch.fnmatch(normalized, pattern_norm) or fnmatch.fnmatch(normalized, f"**/{pattern_norm}")


def _command_matches(command: str, pattern: str) -> bool:
    """Check if a bash command matches a pattern (supports * wildcard)."""
    import re

    if pattern.endswith("*"):
        return command.startswith(pattern[:-1])
    if "*" in pattern:
        regex = re.escape(pattern).replace(r"\*", ".*")
        return bool(re.search(regex, command))
    return command.startswith(pattern) or pattern in command


def _default_permissions(worker_name: str) -> WorkerPermissions:
    """Fallback permissions when config file is unavailable."""
    return WorkerPermissions(
        profile="fallback_restricted",
        read_allow=["**/*"],
        read_deny=[".env", ".env.*", "secrets/**", "keys/**", "credentials/**", "**/*.pem", "**/*.key"],
        write_allow=["src/**", "app/**", "tests/**", "docs/**", "README.md", "*.md"],
        write_ask=["package.json", "requirements.txt", "pyproject.toml"],
        write_deny=[".env", ".env.*", "secrets/**", "keys/**", "credentials/**", "**/*.pem", "**/*.key"],
        bash_allow=["git status", "git diff*", "git log*", "pytest*", "npm test*"],
        bash_ask=["npm install*", "pip install*"],
        bash_deny=["git push*", "git merge*", "rm -rf /", "curl * | sh", "--dangerously-skip-permissions"],
        provider_allow=["deepseek", "mimo"],
        provider_deny=["glm", "glm-5.2", "z_ai"],
        timeout_sec=300,
    )
