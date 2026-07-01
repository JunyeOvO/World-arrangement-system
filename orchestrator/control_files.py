from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


LOCK_TIMEOUT_SEC = 5.0
STALE_LOCK_SEC = 60.0


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path):
        _atomic_write_json(path, data)


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with FileLock(path):
        return _read_json_unlocked(path)


def update_json_file(path: Path, updater: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path):
        payload = _read_json_unlocked(path)
        updated = updater(dict(payload))
        _atomic_write_json(path, updated)
        return updated


class FileLock:
    def __init__(self, path: Path) -> None:
        self.lock_path = path.with_name(f"{path.name}.lock")

    def __enter__(self) -> None:
        deadline = time.monotonic() + LOCK_TIMEOUT_SEC
        while True:
            try:
                self.lock_path.mkdir()
                return None
            except FileExistsError:
                if _remove_stale_lock(self.lock_path):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {self.lock_path}")
                time.sleep(0.02)

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.lock_path.rmdir()
        except OSError:
            pass


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _remove_stale_lock(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    if age < STALE_LOCK_SEC:
        return False
    try:
        lock_path.rmdir()
        return True
    except OSError:
        return False
