from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ArtifactPathError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, task_id: str) -> Path:
        self._validate_segment(task_id)
        path = (self.root / task_id).resolve()
        if not self._inside_root(path):
            raise ArtifactPathError(f"run path escaped artifact root: {path}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, task_id: str, relative: str) -> Path:
        base = self.run_dir(task_id)
        target = (base / relative).resolve()
        if not self._inside_root(target):
            raise ArtifactPathError(f"artifact path escaped artifact root: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, task_id: str, relative: str, payload: Any) -> Path:
        target = self.path(task_id, relative)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        return target

    def append_jsonl(self, task_id: str, relative: str, payload: Any) -> Path:
        target = self.path(task_id, relative)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return target

    def write_text(self, task_id: str, relative: str, text: str) -> Path:
        target = self.path(task_id, relative)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        return target

    def index(self, task_id: str) -> dict[str, str]:
        base = self.run_dir(task_id)
        return {
            str(p.relative_to(base)).replace("\\", "/"): str(p)
            for p in sorted(base.rglob("*"))
            if p.is_file()
        }

    def _inside_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _validate_segment(value: str) -> None:
        if not value or "/" in value or "\\" in value or ".." in value:
            raise ArtifactPathError(f"invalid path segment: {value!r}")

