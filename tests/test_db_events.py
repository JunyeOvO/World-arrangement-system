import json
import sqlite3

from orchestrator.db import SCHEMA, TaskDB
from orchestrator.verifier import CommandResult


def test_append_event_serializes_dataclass_payload(tmp_path):
    db = TaskDB(tmp_path / "state.db")
    db.init()

    db.append_event(
        "t1",
        "verify_failed",
        "VERIFYING",
        "FAILED_FINAL",
        {"verify": {"command_results": [CommandResult("pytest", 1, "test.log", 0.1)]}},
    )

    events = db.list_events("t1")
    payload = json.loads(events[0]["payload_json"])

    assert payload["verify"]["command_results"][0]["command"] == "pytest"


def test_connect_closes_connection_when_caller_raises(tmp_path, monkeypatch):
    closed = []
    real_connect = sqlite3.connect

    class ConnectionProxy:
        def __init__(self, con):
            self._con = con

        def __getattr__(self, name):
            return getattr(self._con, name)

        def close(self):
            closed.append(True)
            return self._con.close()

    def tracking_connect(*args, **kwargs):
        return ConnectionProxy(real_connect(*args, **kwargs))

    monkeypatch.setattr("orchestrator.db.sqlite3.connect", tracking_connect)
    db = TaskDB(tmp_path / "state.db")

    try:
        with db.connect() as con:
            con.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
            raise ValueError("caller failed")
    except ValueError:
        pass

    assert closed == [True]


def test_connect_enables_wal_journal_mode(tmp_path):
    db = TaskDB(tmp_path / "state.db")

    with db.connect() as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(mode).lower() == "wal"
    assert int(timeout) == 3000


def test_ensure_column_treats_duplicate_column_as_idempotent(tmp_path):
    db = TaskDB(tmp_path / "state.db")

    with db.connect() as con:
        con.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        db._ensure_column(con, "sample", "value", "TEXT")

    with db.connect() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(sample)").fetchall()}

    assert "value" in columns


def test_ensure_column_swallows_duplicate_column_race(tmp_path):
    db = TaskDB(tmp_path / "state.db")
    calls = []

    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConnection:
        def execute(self, sql):
            calls.append(sql)
            if sql.startswith("PRAGMA table_info"):
                return FakeCursor()
            raise sqlite3.OperationalError("duplicate column name: value")

    db._ensure_column(FakeConnection(), "sample", "value", "TEXT")  # type: ignore[arg-type]

    assert calls == ["PRAGMA table_info(sample)", "ALTER TABLE sample ADD COLUMN value TEXT"]


def test_ensure_column_reraises_non_duplicate_operational_error(tmp_path):
    db = TaskDB(tmp_path / "state.db")

    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConnection:
        def execute(self, sql):
            if sql.startswith("PRAGMA table_info"):
                return FakeCursor()
            raise sqlite3.OperationalError("no such table: sample")

    try:
        db._ensure_column(FakeConnection(), "sample", "value", "TEXT")  # type: ignore[arg-type]
    except sqlite3.OperationalError as exc:
        assert "no such table" in str(exc)
    else:
        raise AssertionError("expected non-duplicate OperationalError to propagate")


def test_init_dedupes_learned_patterns_before_unique_index(tmp_path):
    path = tmp_path / "state.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        """
        INSERT INTO learned_patterns(
          project_id, task_type, path_pattern, approvals_count,
          success_count, failure_count, rollback_count, confidence,
          active, created_at, updated_at
        )
        VALUES ('proj', 'bugfix', 'src/**', 1, 1, 0, 0, 0.2, 1, 'a', 'a')
        """
    )
    con.execute(
        """
        INSERT INTO learned_patterns(
          project_id, task_type, path_pattern, approvals_count,
          success_count, failure_count, rollback_count, confidence,
          active, created_at, updated_at
        )
        VALUES ('proj', 'bugfix', 'src/**', 2, 0, 1, 0, 0.7, 0, 'b', 'b')
        """
    )
    con.commit()
    con.close()

    db = TaskDB(path)
    db.init()

    patterns = db.get_learned_patterns("proj", active_only=False)
    assert len(patterns) == 1
    assert patterns[0]["approvals_count"] == 3
    assert patterns[0]["success_count"] == 1
    assert patterns[0]["failure_count"] == 1
    assert patterns[0]["confidence"] == 0.7


def test_upsert_learned_pattern_uses_unique_conflict(tmp_path):
    db = TaskDB(tmp_path / "state.db")
    now = "2026-07-01T00:00:00Z"
    row = {
        "project_id": "proj",
        "task_type": "bugfix",
        "path_pattern": "src/**",
        "worker": "claude_code",
        "model": "deepseek_pro",
        "variant": "default",
        "approvals_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "rollback_count": 0,
        "trust_score": 0.0,
        "confidence": 0.2,
        "suggested_mode": "AUTO_WITH_SUMMARY",
        "active": True,
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
    }

    db.upsert_learned_pattern(row)
    db.upsert_learned_pattern({**row, "success_count": 0, "failure_count": 1, "confidence": 0.8})

    patterns = db.get_learned_patterns("proj", active_only=False)
    assert len(patterns) == 1
    assert patterns[0]["approvals_count"] == 2
    assert patterns[0]["success_count"] == 1
    assert patterns[0]["failure_count"] == 1
    assert patterns[0]["confidence"] == 0.8
