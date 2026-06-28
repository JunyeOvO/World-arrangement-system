from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectIndicator:
    """A single detection signal found during project profiling."""

    name: str  # e.g. "pyproject.toml", ".git", "android/app/build.gradle"
    path: str  # relative path within repo
    project_type: str  # "python", "node", "android", "unity", "maven", ...
    weight: float  # 0.0-1.0 contribution to confidence
    matched_by: str = "file"  # "file" | "directory" | "content" | "nested"


@dataclass
class ProjectProfile:
    """Full profile of a discovered project."""

    project_id: str
    name: str
    repo: str  # absolute or ~/ path
    project_type: str  # "node" | "python" | "android" | "unity" | "maven" | "vite" | "next" | "docker" | "unknown"
    stack: list[str] = field(default_factory=list)  # e.g. ["python", "fastapi", "postgresql"]
    confidence: float = 0.0
    status: str = "pending_confirmation"  # "active" | "pending_confirmation" | "ignored"
    auto_generated: bool = True
    indicators: list[dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""
    needs_refresh: bool = False
    first_seen: str = ""
    last_seen: str = ""
    project_group: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.first_seen:
            self.first_seen = now
        if not self.last_seen:
            self.last_seen = now


@dataclass
class ProjectFingerprint:
    """Fingerprint hash and supporting data for change detection."""

    project_id: str
    hash: str
    file_tree: list[str] = field(default_factory=list)
    key_files: dict[str, str] = field(default_factory=dict)  # path -> sha256
    computed_at: str = ""

    def __post_init__(self) -> None:
        if not self.computed_at:
            self.computed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ScanResult:
    """Result of scanning root directories for project candidates."""

    candidates: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    roots_scanned: list[str] = field(default_factory=list)
