import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orchestrator import control_files
from orchestrator.control_files import read_json_file, update_json_file, write_json_file


def test_update_json_file_holds_one_lock_and_preserves_prior_state(tmp_path: Path):
    target = tmp_path / "control" / "process.json"
    write_json_file(target, {"pid": 1, "status": "running"})

    updated = update_json_file(target, lambda payload: {**payload, "status": "cancelled"})

    assert updated == {"pid": 1, "status": "cancelled"}
    assert not target.with_name("process.json.lock").exists()


def test_file_lock_removes_stale_lock_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(control_files, "STALE_LOCK_SEC", 0)
    target = tmp_path / "process.json"
    lock = target.with_name("process.json.lock")
    lock.mkdir()
    old = time.time() - 120
    os.utime(lock, (old, old))

    write_json_file(target, {"status": "ok"})

    assert target.read_text(encoding="utf-8")
    assert not lock.exists()


def test_update_json_file_serializes_concurrent_read_modify_write(tmp_path: Path):
    target = tmp_path / "process.json"
    write_json_file(target, {"count": 0})

    def increment() -> None:
        update_json_file(target, lambda payload: {"count": int(payload.get("count") or 0) + 1})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: increment(), range(40)))

    assert read_json_file(target)["count"] == 40
