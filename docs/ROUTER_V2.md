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
- `task_shape`
- `budget_estimate_usd`
- `budget_cap_usd`
- `history_basis`

## Key Decisions

- README architecture explanation routes to ClaudeCodeWorker + DeepSeek, not high-risk architecture.
- Auth/payment/database docs remain docs unless the action modifies code or production data.
- Explicit GLM-5.2 routes to OpenCodeWorker after SafetyGate.
- Screenshot analysis routes to `claude code + Mimo V2.5`.
- Screenshot-to-code routes to `claude code + Mimo V2.5 pro`.
- Hard bugfix routes to OpenCodeWorker + GLM-5.2 `max`.

## History-Aware Routing

`plan_route(task, project, history=None)` accepts historical model metrics from
`Database.model_metrics_summary()`. Each row should contain:

- `model`
- `worker`
- `attempts`
- `success_rate`
- `avg_cost_usd`

The router uses history as a bounded secondary signal, after safety gates and
hard task rules:

- Safety blocks, explicit GLM requests, multimodal requirements, and hard
  bugfix rules still win over cost optimization.
- Candidate scoring adds a small success/cost delta when the same worker/model
  has enough prior evidence.
- Router V3 uses `task_shape` to choose between allowed ClaudeCode models.
  For docs and single-file targeted patches, strong low-cost flash history can
  select `deepseek_flash`.
- Poor flash history selects `deepseek_pro` even when flash is cheaper.
- Very small sample history is intentionally weak and should not flip default
  patch routes by itself.
- The selected route explains the evidence through `history_basis` and the
  `history_decision` fragment in `reason`.

## Test Coverage

Router V2 behavior is covered by:

- `tests/test_router.py`
- `tests/test_routing_v2.py`
- `tests/test_opencode_variant.py`
- `tests/test_workers.py`
