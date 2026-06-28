from pathlib import Path

from orchestrator.db import TaskDB
from orchestrator.console.streams import sse_stream


def test_sse_stream_orders_events_without_duplicates(tmp_path: Path):
    db = TaskDB(tmp_path / "state.db")
    db.init()
    for idx in range(50):
        db.append_event(f"task-{idx}", "created", None, "QUEUED", {"idx": idx})

    chunks = list(sse_stream(db, after_id=0, max_events=50))
    text = b"".join(chunks).decode("utf-8")

    assert text.count("event: task.created") == 50
    assert "id: 1\n" in text
    assert "id: 50\n" in text
    assert text.index("id: 1\n") < text.index("id: 50\n")


def test_sse_stream_emits_stale_heartbeat_alert(tmp_path: Path):
    db = TaskDB(tmp_path / "state.db")
    db.init()
    db.upsert_worker_heartbeat({
        "worker_id": "worker-a",
        "task_id": "task-a",
        "attempt_id": "attempt-a",
        "ts": "2020-01-01T00:00:00Z",
        "status": "EXECUTING",
        "phase": "EXECUTING",
    })

    chunks = list(sse_stream(db, after_id=0, max_events=1))

    assert b"event: alert.opened" in b"".join(chunks)

