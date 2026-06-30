from __future__ import annotations

import json

from orchestrator.failure_classifier import FailureClassification
from orchestrator.read_only_salvage import ReadOnlySalvagePolicy, extract_worker_partial_text
from orchestrator.workers.base import WorkerResult


def test_code_contract_silent_max_turns_salvages_structured_thinking(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    thinking = (
        "## Summary of the Contract\n\n"
        "Producer: js/three-work-area.js resolveAnchored3DWorkArea.\n"
        "Consumer: js/render/map-3d.js normalizeWorkArea.\n"
        "Mismatch risk: medium. The producer adds anchor fields while the consumer "
        "reconstructs a normalized workArea object and can silently drop future contract fields.\n"
        "Next step: add a focused contract test for workArea normalization.\n"
    )
    stream.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "thinking",
                                    "thinking": thinking,
                                }
                            ]
                        },
                    }
                ),
                json.dumps({"type": "result", "subtype": "error_max_turns"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    worker_result = WorkerResult(
        status="failed",
        summary="Claude Code worker failed",
        changed_files=[],
        stdout_path=str(stream),
    )
    failure = FailureClassification("silent_max_turns_no_output", True, "seed_evidence_or_reduce_tool_budget")

    result = ReadOnlySalvagePolicy().salvage(
        {
            "task_mode": "read_only",
            "expected_diff": False,
            "read_budget_profile": "code_contract_audit",
        },
        worker_result,
        failure,
    )

    assert result is not None
    assert result.source == "worker_stream"
    assert "Producer: js/three-work-area.js" in result.summary
    assert "Mismatch risk: medium" in result.summary
    assert worker_result.partial_result is True


def test_generic_short_thinking_is_not_salvaged(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "thinking", "thinking": "Need to inspect more files first."}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert extract_worker_partial_text(stream, task={"read_budget_profile": "quick_triage"}) is None


def test_salvage_policy_ignores_patch_tasks(tmp_path):
    stream = tmp_path / "worker.stream.jsonl"
    stream.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Summary with risks and next step."}]}}),
        encoding="utf-8",
    )
    worker_result = WorkerResult(status="failed", summary="failed", changed_files=[], stdout_path=str(stream))
    failure = FailureClassification("max_turns_no_diff", True, "retry")

    result = ReadOnlySalvagePolicy().salvage({"task_mode": "patch", "expected_diff": True}, worker_result, failure)

    assert result is None
    assert worker_result.partial_result is False
