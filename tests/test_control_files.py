import os
import time
from pathlib import Path

from orchestrator import control_files
from orchestrator.control_files import update_json_file, write_json_file


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
