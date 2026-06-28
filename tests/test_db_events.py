import json

from orchestrator.db import TaskDB
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
