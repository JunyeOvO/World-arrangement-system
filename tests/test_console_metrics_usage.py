from orchestrator.console.metrics_usage import build_metrics_usage, metric_date, session_label


def test_build_metrics_usage_groups_cost_by_day_and_model():
    payload = build_metrics_usage(
        [
            {
                "created_at": "2026-06-28T13:12:00Z",
                "model": "GLM-5.2",
                "worker": "Opencode",
                "input_tokens": 45978,
                "output_tokens": 74,
                "cache_read_input_tokens": 0,
                "task_id": "task_metrics_a",
                "attempt_no": 1,
            },
            {
                "created_at": "2026-06-28T13:15:00Z",
                "model": "GLM-5.2",
                "worker": "Opencode",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cache_read_input_tokens": 500,
                "task_id": "task_metrics_b",
                "attempt_no": 2,
            },
        ]
    )

    assert payload["cost_series"]["dates"] == ["2026-06-28"]
    assert payload["cost_series"]["models"] == ["GLM-5.2"]
    assert payload["cost_series"]["rows"] == [
        {"date": "2026-06-28", "model": "GLM-5.2", "cost_usd": 0.066665}
    ]
    assert payload["calls"][0]["session"] == "etrics_a"
    assert payload["calls"][1]["attempt_no"] == 2


def test_build_metrics_usage_defaults_missing_values():
    payload = build_metrics_usage([{"task_id": "", "model": "", "created_at": ""}])

    assert payload["cost_series"]["dates"] == ["unknown"]
    assert payload["cost_series"]["models"] == ["unknown"]
    assert payload["calls"] == [{
        "created_at": "",
        "date": "unknown",
        "model": "unknown",
        "worker": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0,
        "task_id": "",
        "attempt_no": None,
        "session": "",
    }]


def test_metric_date_and_session_label_helpers():
    assert metric_date("2026-07-01T00:00:00Z") == "2026-07-01"
    assert metric_date("") == "unknown"
    assert session_label("short") == "short"
    assert session_label("t_20260701_abcdef12") == "abcdef12"
