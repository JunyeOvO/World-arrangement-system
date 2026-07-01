from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .ignore_manager import ensure_world_ignored


WritePolicy = Literal["zero_write", "ignored_write", "adapter_file", "full_project_mode"]
RuntimeBackend = Literal["external-global", "external-temp", "repo-local-ignored"]


@dataclass(frozen=True)
class RuntimeResolution:
    project_id: str
    backend: RuntimeBackend
    project_dir: Path
    run_dir: Path | None = None


def world_home() -> Path:
    return Path(os.environ.get("WORLD_HOME", Path.home() / ".world")).expanduser().resolve()


def resolve_project_id(repo_path: str | Path) -> str:
    repo = str(Path(repo_path).expanduser().resolve()).replace("\\", "/").lower()
    return hashlib.sha256(repo.encode("utf-8")).hexdigest()[:16]


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".world-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


class RuntimeStore:
    """World external runtime store.

    The default policy is zero_write: all profiles, plans, DAGs, worker results,
    patches, and verification reports live outside the business repository.
    """

    def __init__(self, repo_path: str | Path, write_policy: WritePolicy = "zero_write"):
        self.repo_path = Path(repo_path).expanduser().resolve()
        self.write_policy = write_policy
        self.project_id = resolve_project_id(self.repo_path)
        self.backend = self.resolve_backend()
        self.project_dir = self._project_dir_for_backend(self.backend)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def resolve_backend(self) -> RuntimeBackend:
        global_projects = world_home() / "projects"
        if _is_writable_dir(global_projects):
            return "external-global"

        temp_projects = Path(tempfile.gettempdir()) / "world-runs"
        if _is_writable_dir(temp_projects):
            return "external-temp"

        if self.write_policy == "ignored_write":
            ensure_world_ignored(self.repo_path)
            return "repo-local-ignored"

        raise RuntimeError("RuntimeStoreUnavailable: no external World runtime backend is writable")

    def _project_dir_for_backend(self, backend: RuntimeBackend) -> Path:
        if backend == "external-global":
            return world_home() / "projects" / self.project_id
        if backend == "external-temp":
            return Path(tempfile.gettempdir()) / "world-runs" / self.project_id
        return self.repo_path / ".world"

    def resolve_run_dir(self, run_id: str) -> Path:
        run_dir = self.project_dir / "runs" / _safe_path_segment(run_id, "run_id")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def resolution(self, run_id: str | None = None) -> RuntimeResolution:
        return RuntimeResolution(
            project_id=self.project_id,
            backend=self.backend,
            project_dir=self.project_dir,
            run_dir=self.resolve_run_dir(run_id) if run_id else None,
        )

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self.project_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_project_profile(self, profile: dict[str, Any]) -> Path:
        profile = dict(profile)
        profile.setdefault("project_id", self.project_id)
        profile.setdefault("repo_path", str(self.repo_path))
        profile.setdefault("write_policy", self.write_policy)
        profile.setdefault("world_runtime_mode", self.backend)
        return self.write_json("project.profile.json", profile)

    def write_plan(self, run_id: str, plan: dict[str, Any]) -> Path:
        safe_run_id = _safe_path_segment(run_id, "run_id")
        return self.write_json(f"runs/{safe_run_id}/plan.json", plan)

    def write_dag(self, run_id: str, dag: dict[str, Any]) -> Path:
        safe_run_id = _safe_path_segment(run_id, "run_id")
        return self.write_json(f"runs/{safe_run_id}/dag.json", dag)

    def write_worker_result(self, run_id: str, task_id: str, result: dict[str, Any]) -> Path:
        safe_run_id = _safe_path_segment(run_id, "run_id")
        safe_task_id = _safe_path_segment(task_id, "task_id")
        return self.write_json(
            f"runs/{safe_run_id}/worker-results/{safe_task_id}.json",
            result,
        )

    def write_patch(self, run_id: str, task_id: str, patch_text: str) -> Path:
        safe_run_id = _safe_path_segment(run_id, "run_id")
        safe_task_id = _safe_path_segment(task_id, "task_id")
        path = self.project_dir / "runs" / safe_run_id / "patches" / f"{safe_task_id}.patch"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(patch_text, encoding="utf-8")
        return path

    def write_verification(self, run_id: str, report: dict[str, Any]) -> Path:
        safe_run_id = _safe_path_segment(run_id, "run_id")
        return self.write_json(f"runs/{safe_run_id}/verification/verification_report.json", report)

    def cleanup(self, run_id: str | None = None, mode: Literal["safe", "force"] = "safe") -> None:
        project_dir = self.project_dir.resolve()
        if run_id:
            target = (project_dir / "runs" / _safe_path_segment(run_id, "run_id")).resolve()
            target.relative_to(project_dir / "runs")
        else:
            target = project_dir
        if not target.exists():
            return
        if mode != "force" and target == self.repo_path:
            raise RuntimeError("refusing to cleanup repository root")
        target.relative_to(project_dir)
        shutil.rmtree(target)


def _safe_path_segment(value: str, field: str) -> str:
    text = str(value or "")
    if not text or text in {".", ".."}:
        raise ValueError(f"invalid {field}: empty or relative segment")
    if "/" in text or "\\" in text:
        raise ValueError(f"invalid {field}: path separators are not allowed")
    if Path(text).name != text:
        raise ValueError(f"invalid {field}: must be a single path segment")
    return text
