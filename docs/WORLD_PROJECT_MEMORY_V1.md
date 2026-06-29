# World Project Memory v1

Project Memory v1 is a bounded local context cache for World workers.

## Goal

Reduce repeated project re-discovery by giving each worker a compact, redacted project summary before it reads files.

This is not a semantic vector memory system yet. It is the minimum useful layer needed to measure whether cached project context reduces worker reads, input tokens, and repeated Codex planning effort.

## Storage

Memory is stored outside the business repository through `RuntimeStore`:

```text
%WORLD_HOME%/projects/<runtime_id>/memory/project_memory.json
```

The business repo remains zero-write by default.

## Contents

The cache stores:

- project id and repo path
- stack
- test/build commands
- forbidden paths
- selected file summaries
- per-file content hash
- memory hit/miss/skipped counts

Large files over 256 KB are skipped. Common generated/runtime directories are skipped.

## Prompt Use

`submit-task` refreshes project memory before execution and embeds a compact `## Project Memory` section into the worker prompt.

Workers are instructed to use this cached context before reading files. If a referenced file may have changed, they should verify the file directly.

## Invalidation

File summaries are reused only when the file content hash matches the previous memory entry. Changed or new files are re-summarized. Deleted files disappear from the next memory snapshot.

## Safety

Memory summaries are redacted before storage and prompt injection:

- `sk-*` style API keys are replaced.
- common key/value secret fields such as `API_KEY`, `SECRET`, `TOKEN`, `PASSWORD`, and `CREDENTIAL` are redacted.

The cache should not be treated as a source of truth for secrets or production configuration.

## Metrics

Task metrics now include:

- `memory_hit_count`
- `memory_miss_count`

These fields are the first step toward measuring whether Project Memory reduces repeated context reads and token cost.

## Current Limits

- No vector retrieval.
- No symbol graph.
- No task-memory promotion rules.
- No counterfactual Codex-token estimate yet.

Those belong to later Project Memory versions after this v1 cache proves useful in real tasks.
