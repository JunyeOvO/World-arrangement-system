import json

from orchestrator.db import TaskDB
from orchestrator.metrics import collect_task_metrics, parse_worker_stream, write_metrics


def test_parse_claude_stream_result_metrics(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(
        json.dumps({"type": "system", "subtype": "init"}) + "\n"
        + json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "total_cost_usd": 0.123,
                "duration_ms": 1200,
                "duration_api_ms": 900,
                "num_turns": 4,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 10,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_worker_stream(stream)

    assert parsed["total_cost_usd"] == 0.123
    assert parsed["num_turns"] == 4
    assert parsed["input_tokens"] == 100
    assert parsed["output_tokens"] == 50
    assert parsed["cache_read_input_tokens"] == 10


def test_metrics_write_and_db_summary(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(json.dumps({"total_cost_usd": 0.2, "num_turns": 2}) + "\n", encoding="utf-8")
    metrics = collect_task_metrics(
        task_id="t1",
        attempt_no=1,
        worker="claude_code",
        model="deepseek_pro",
        status="success",
        stream_path=str(stream),
        changed_files_count=2,
    )
    out = write_metrics(metrics, tmp_path / "metrics.json")
    db = TaskDB(tmp_path / "state.sqlite")
    db.upsert_task_metrics(metrics.to_dict())

    assert json.loads(out.read_text(encoding="utf-8"))["changed_files_count"] == 2
    assert db.list_task_metrics("t1")[0]["total_cost_usd"] == 0.2
    assert db.model_metrics_summary()[0]["model"] == "deepseek_pro"
