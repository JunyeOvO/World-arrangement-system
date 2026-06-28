# World Router V2

World Router V2 replaces linear keyword routing with explainable candidate routing.

## Pipeline

```text
task.json
  -> FeatureExtractor
  -> TaskClassifier
  -> SafetyGate
  -> CandidateBuilder
  -> CandidateScorer
  -> ConflictResolver
  -> PolicyOverride
  -> RouteDecision
```

## Compatibility

The public Python API remains:

```python
plan_route(task, project, history=None)
```

Returned routes still include:

- `selected_worker`
- `selected_model`
- `fallback_models`
- `max_retries`
- `escalation_policy`

V2 adds:

- `selected_agent`
- `selected_llm`
- `agent_llm`
- `intensity`
- `variant`
- `capability_tier`
- `capability_profile`
- `confidence`
- `task_labels`
- `matched_rules`
- `rejected_candidates`
- `retry_chain`

## Key Decisions

- README architecture explanation routes to ClaudeCodeWorker + DeepSeek, not high-risk architecture.
- Auth/payment/database docs remain docs unless the action modifies code or production data.
- Explicit GLM-5.2 routes to OpenCodeWorker after SafetyGate.
- Screenshot analysis routes to `claude code + Mimo V2.5`.
- Screenshot-to-code routes to `claude code + Mimo V2.5 pro`.
- Hard bugfix routes to OpenCodeWorker + GLM-5.2 `max`.

## Test Coverage

Router V2 behavior is covered by:

- `tests/test_router.py`
- `tests/test_routing_v2.py`
- `tests/test_opencode_variant.py`
- `tests/test_workers.py`
