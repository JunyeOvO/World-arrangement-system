import json

from orchestrator.db import TaskDB
from orchestrator.attempt_recording import AttemptMetricsRecorder
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


def test_parse_claude_message_usage_and_ignore_thinking_tokens(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(
        json.dumps({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 12}) + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cache_read_input_tokens": 5,
                    }
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 3,
                        "cache_read_input_tokens": 7,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_worker_stream(stream)

    assert parsed["input_tokens"] == 21
    assert parsed["output_tokens"] == 5
    assert parsed["cache_read_input_tokens"] == 12
    assert parsed.get("failure_reason") is None


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
        memory_hit_count=3,
        memory_miss_count=1,
    )
    out = write_metrics(metrics, tmp_path / "metrics.json")
    db = TaskDB(tmp_path / "state.sqlite")
    db.upsert_task_metrics(metrics.to_dict())

    assert json.loads(out.read_text(encoding="utf-8"))["changed_files_count"] == 2
    assert db.list_task_metrics("t1")[0]["total_cost_usd"] == 0.2
    assert db.list_task_metrics("t1")[0]["memory_hit_count"] == 3
    assert db.list_task_metrics("t1")[0]["memory_miss_count"] == 1
    assert db.model_metrics_summary()[0]["model"] == "deepseek_pro"


def test_attempt_metrics_recorder_writes_metrics_and_token_ledger(tmp_path):
    run_dir = tmp_path / "run"
    worker_dir = run_dir / "worker"
    worker_dir.mkdir(parents=True)
    stream = worker_dir / "worker.stream.jsonl"
    stream.write_text(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "total_cost_usd": 0.25,
                "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 50},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "task.json").write_text(
        json.dumps(
            {
                "project_memory": {
                    "memory": {"stats": {"hit_count": 4, "miss_count": 2}},
                }
            }
        ),
        encoding="utf-8",
    )
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": "t_recorder",
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "inspect project",
            "status": "EXECUTING",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(run_dir),
        }
    )

    class Result:
        status = "success"
        stdout_path = str(stream)
        changed_files = ["app.py"]

    recorder = AttemptMetricsRecorder(db)
    recorder.write_attempt_metrics(
        "t_recorder",
        1,
        {"worker": "claude_code", "model": "deepseek_pro"},
        Result(),
        None,
        build_passed=True,
        review_approved=True,
    )

    attempt_metrics = json.loads((run_dir / "attempts" / "01" / "metrics.json").read_text(encoding="utf-8"))
    history_lines = (run_dir / "metrics_history.jsonl").read_text(encoding="utf-8").splitlines()
    ledger = json.loads((run_dir / "token_ledger.json").read_text(encoding="utf-8"))
    row = db.list_task_metrics("t_recorder")[0]

    assert attempt_metrics["memory_hit_count"] == 4
    assert json.loads(history_lines[0])["attempt_no"] == 1
    assert attempt_metrics["memory_miss_count"] == 2
    assert attempt_metrics["changed_files_count"] == 1
    assert row["total_cost_usd"] == 0.25
    assert ledger["worker"]["total_tokens"] == 1250


def test_attempt_metrics_history_preserves_multiple_attempts(tmp_path):
    run_dir = tmp_path / "runs" / "t_recorder"
    stream = run_dir / "worker" / "worker.stream.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text(
        "\n".join([
            json.dumps({"type": "usage", "input_tokens": 100, "output_tokens": 10, "total_cost_usd": 0.01}),
        ]),
        encoding="utf-8",
    )
    db = TaskDB(tmp_path / "state.sqlite")
    db.create_task(
        {
            "task_id": "t_recorder",
            "project_id": "p1",
            "repo_path": str(tmp_path),
            "user_goal": "inspect project",
            "status": "EXECUTING",
            "created_at": "2026-06-30T01:00:00Z",
            "updated_at": "2026-06-30T01:00:01Z",
            "run_dir": str(run_dir),
        }
    )

    class Result:
        status = "success"
        stdout_path = str(stream)
        changed_files = []

    recorder = AttemptMetricsRecorder(db)
    recorder.write_attempt_metrics("t_recorder", 1, {"worker": "claude_code", "model": "deepseek_pro"}, Result(), None)
    recorder.write_attempt_metrics("t_recorder", 2, {"worker": "claude_code", "model": "deepseek_pro"}, Result(), None)

    history = [json.loads(line) for line in (run_dir / "metrics_history.jsonl").read_text(encoding="utf-8").splitlines()]
    latest = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    assert [row["attempt_no"] for row in history] == [1, 2]
    assert latest["attempt_no"] == 2
