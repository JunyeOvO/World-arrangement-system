# World Capability Assessment and Upgrade Plan

Date: 2026-06-29

## External Capability Boundary

Comparable systems show the same practical boundary: an agentic coding system is useful when it narrows context, routes work to the right execution backend, records evidence, and keeps human control over high-risk changes. It does not automatically save tokens just because it uses multiple agents. Poor decomposition can increase total tokens through repeated repository scans, duplicated planning, failed retries, and review overhead.

Reference systems reviewed:

- OpenAI Codex / coding agents: asynchronous code tasks are useful for bounded repository work, but still require clear tasks, review, and test evidence.
- Claude Code / subagent-style workflows: useful for context isolation and specialized execution, but delegation needs strict task specs and output contracts.
- LangGraph / supervisor multi-agent patterns: useful for explicit routing and stateful orchestration; handoff boundaries are part of the system design.
- Microsoft AutoGen / multi-agent conversations: strong for structured agent collaboration, but human-in-the-loop and termination criteria remain necessary.
- SWE-agent / OpenHands / Devin-style systems: demonstrate real software engineering automation on benchmark tasks, but success is constrained by repo setup, test availability, environment reproducibility, and task scope.

## Current World Reality

World currently has the minimum real production spine:

- Registered-project execution path through `ai-dispatcher`.
- Route selection across `Claudecode` and `Opencode`.
- Supported model display names: `Deepseek-V4-flash`, `Deepseek-V4-pro`, `Mimo-V2.5`, `Mimo-V2.5-pro`, `GLM-5.2`.
- Isolated run artifacts and task status tracking.
- Console status grouping and task detail pages.
- Token capture for worker attempts.
- Backend-computed cost from real token usage and official token pricing.
- Safety boundaries for env files, secrets, dangerous commands, and approval states.

## Measured Efficiency

Current local `task_metrics` snapshot:

| Metric | Value |
|---|---:|
| Attempts | 32 |
| Priced attempts | 32 |
| Missing token rows | 4 |
| Input tokens | 1,874,842 |
| Cache read input tokens | 13,390,700 |
| Output tokens | 170,163 |
| Total recorded worker tokens | 15,435,705 |
| Cache read ratio | 87.72% |
| Actual computed cost | $1.950260 |
| Same-token GLM-5.2 baseline | $6.855077 |
| Computed cost saved | $4.904817 |
| Computed cost saving rate | 71.55% |

By model:

| Agent | Model | Attempts | Tokens | Actual cost | GLM baseline | Saved |
|---|---|---:|---:|---:|---:|---:|
| Claudecode | Deepseek-V4-pro | 13 | 5,948,550 | $0.394099 | $2.669675 | $2.275576 |
| Claudecode | Mimo-V2.5 | 4 | 2,302,106 | $0.060750 | $1.077517 | $1.016767 |
| Claudecode | Deepseek-V4-flash | 5 | 1,999,344 | $0.042380 | $0.871429 | $0.829049 |
| Claudecode | Mimo-V2.5-pro | 3 | 1,991,957 | $0.150864 | $0.934289 | $0.783425 |
| Opencode | GLM-5.2 | 7 | 3,193,748 | $1.302167 | $1.302167 | $0.000000 |

## What This Proves

World currently has a measurable cost-saving capability: routing a large share of attempts away from GLM-5.2 and into lower-cost models reduced computed model cost by about 71.55% versus an all-GLM same-token baseline.

World does not yet strictly prove total token savings versus manual Codex execution. It records worker token usage, but it does not yet record an equivalent no-World Codex baseline for the same task. Therefore:

- Cost saving: measured.
- Worker token usage: measured.
- Codex main-thread token saving: inferred, not measured.
- End-to-end business productivity gain: promising but not yet benchmarked.

## Real Development Readiness

Current suitable use:

- Project quality audits.
- Read-only diagnosis.
- Docs and README updates.
- Small to medium bug fixes.
- Test generation or focused test repair.
- UI/visual analysis when MiMo routes are available.
- Complex bounded code tasks when OpenCode/GLM is available and tests exist.

Current unsafe or weak use:

- Fully autonomous large feature delivery.
- Multi-repo changes.
- Production auth/payment/database changes without approval.
- Tasks with unavailable local setup or missing tests.
- Tasks requiring guaranteed retry/resume semantics.
- Claims of Codex token savings without a measured baseline.

## Upgrade Plan

### P0: Measured Efficiency Reporting

Status: implemented.

- Add backend efficiency endpoint.
- Compute actual cost from real token usage.
- Compare against same-token GLM-5.2 baseline.
- Surface savings, token volume, cache ratio, and missing token rows in Console.
- Keep Codex-token savings marked as not directly measured.

### P1: Task Outcome Quality Matrix

Add outcome metrics by task class:

- task_type
- risk_level
- selected agent/model
- success/failure outcome
- changed files count
- verification result
- user accepted/rejected/dismissed

Goal: decide whether low-cost routes are actually good enough, not merely cheap.

### P2: Codex Baseline Measurement

Add an optional baseline mode:

- record estimated manual Codex prompt tokens for each `/world` task
- record dispatcher prompt length
- record worker input/output/cache tokens
- record final summary length returned to Codex

Goal: measure main-thread compression ratio and avoid pretending that cost saving equals token saving.

### P3: Context Pack Cache

Generate reusable project context packs:

- repo summary
- stack summary
- test commands
- risk boundaries
- hot files
- known architecture decisions

Goal: reduce repeated worker repository scans and improve first-attempt success.

### P4: Production Project Health Gate

Before dispatch:

- verify repo path exists
- verify git status
- verify configured test commands
- verify model/worker availability
- verify World runtime path is outside business repo

Goal: avoid wasted worker tokens on broken project registrations.

### P5: Retry and Resume Semantics

Replace current manual retry limitation with explicit retry policy:

- retry only from terminal failed states
- create new attempt with inherited task spec
- do not resume unknown process state
- carry forward failure evidence
- cap retries by risk and cost budget

Goal: reduce failed-task dead ends without unsafe process resurrection.

### P6: Real Business Eval Suite

Create a small recurring eval set per project:

- 5 read-only diagnosis tasks
- 5 docs/test tasks
- 5 small code-change tasks
- 5 high-risk approval-gated tasks

Metrics:

- success rate
- accepted output rate
- computed cost
- token volume
- time to result
- rework count

Goal: prove whether World helps real development instead of relying on anecdotal examples.

## Immediate Acceptance Criteria

- Console shows computed cost, not adapter-reported cost.
- Console shows real token usage.
- Console shows same-token GLM baseline and savings rate.
- Console clearly states Codex token savings are not directly measured yet.
- Tests cover token-cost calculation and alias merging.

