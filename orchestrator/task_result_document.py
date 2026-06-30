from __future__ import annotations

from typing import Any


def build_final_markdown(
    task: dict[str, Any],
    route: dict[str, Any],
    worker: dict[str, Any],
    verify_result: dict[str, Any],
    review: dict[str, Any],
) -> str:
    status_line = "degraded_mock_result" if worker.get("mock_result") or worker.get("degraded") else "completed"
    review_verdict = "not approved for publish" if review.get("degraded") else ("approved" if review.get("approved") else "not approved")
    degraded_note = ""
    if review.get("degraded") or worker.get("degraded"):
        degraded_note = f"""
## Degraded Result

This result is not a real worker audit or implementation.

- Reason: {review.get('degradation_reason') or worker.get('degradation_reason')}
- Review verdict: {review_verdict}
- Publish allowed: false
"""
    return f"""# Task Result

## Summary

- Task: {task['user_goal']}
- Project: {task['project_id']}
- Worker: {route['selected_worker']}
- Model: {route['selected_model']}
- Status: {status_line}
{degraded_note}

## Worker

{worker.get('summary', '')}

## Verification

- Tests passed: {verify_result.get('tests_passed')}
- Build passed: {verify_result.get('build_passed')}

## Review

- Mode: {review.get('review_mode', 'unknown')}
- Degraded: {review.get('degraded', False)}
- Degradation reason: {review.get('degradation_reason')}
- Verdict: {review_verdict}
- Publish allowed: {bool(review.get('can_create_pr'))}

## Safety

V1 never auto-merges PRs.
"""
