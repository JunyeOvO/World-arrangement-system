# Codex Evaluation Harness

This lightweight harness tracks whether local Codex work in the World repository is improving over repeated tasks.

## 30-Task Log

| # | Date | Task | Result | Rework Needed | User Correction | Invalid Command | High-Risk Action Intercepted | Verification Evidence |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-29 | Bootstrap project-local SAPIEN-Lite workflow scaffold | Pass | No | No | No | No | `Test-Path`, `rg` structure scan, `git diff --check`, `git status --short --branch` |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |  |  |
| 9 |  |  |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |  |  |
| 11 |  |  |  |  |  |  |  |  |
| 12 |  |  |  |  |  |  |  |  |
| 13 |  |  |  |  |  |  |  |  |
| 14 |  |  |  |  |  |  |  |  |
| 15 |  |  |  |  |  |  |  |  |
| 16 |  |  |  |  |  |  |  |  |
| 17 |  |  |  |  |  |  |  |  |
| 18 |  |  |  |  |  |  |  |  |
| 19 |  |  |  |  |  |  |  |  |
| 20 |  |  |  |  |  |  |  |  |
| 21 |  |  |  |  |  |  |  |  |
| 22 |  |  |  |  |  |  |  |  |
| 23 |  |  |  |  |  |  |  |  |
| 24 |  |  |  |  |  |  |  |  |
| 25 |  |  |  |  |  |  |  |  |
| 26 |  |  |  |  |  |  |  |  |
| 27 |  |  |  |  |  |  |  |  |
| 28 |  |  |  |  |  |  |  |  |
| 29 |  |  |  |  |  |  |  |  |
| 30 |  |  |  |  |  |  |  |  |

## Metrics

- Success rate: count tasks with `Result=Pass`.
- Rework rate: count tasks with `Rework Needed=Yes`.
- Correction rate: count tasks with `User Correction=Yes`.
- Invalid command rate: count tasks with `Invalid Command=Yes`.
- High-risk interception rate: count tasks with `High-Risk Action Intercepted=Yes`.

## Review Questions

- Did the task stay within the stated repository scope?
- Were expected observations recorded before risky checks?
- Was verification concrete enough for the next agent to trust?
- Did any failure become a test, script, documentation note, or workflow rule?
