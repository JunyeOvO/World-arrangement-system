from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .constants import DEFAULT_HOME


@dataclass(frozen=True)
class OrchestratorPaths:
    code_root: Path
    home: Path
    runs: Path
    state_db: Path
    projects_yaml: Path
    models_yaml: Path
    policies_yaml: Path


def code_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_home() -> Path:
    return Path(os.environ.get("AI_ORCHESTRATOR_HOME", DEFAULT_HOME)).expanduser().resolve()


def paths() -> OrchestratorPaths:
    home = runtime_home()
    return OrchestratorPaths(
        code_root=code_root(),
        home=home,
        runs=home / "runs",
        state_db=home / "state.sqlite",
        projects_yaml=home / "projects.yaml",
        models_yaml=home / "models.yaml",
        policies_yaml=home / "policies.yaml",
    )


def ensure_runtime_dirs() -> OrchestratorPaths:
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    p.runs.mkdir(parents=True, exist_ok=True)
    return p


def load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or default
    return data


def load_models() -> dict[str, Any]:
    p = paths()
    return load_yaml(p.models_yaml, {"models": {}})


def load_policies() -> dict[str, Any]:
    p = paths()
    fallback = p.code_root / "config" / "policies.yaml.example"
    if p.policies_yaml.exists():
        return load_yaml(p.policies_yaml, {})
    return load_yaml(fallback, {})

