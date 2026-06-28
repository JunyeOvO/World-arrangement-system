# Security

## Non-Negotiable Rules

- No auto-merge.
- No force push.
- No secrets in repository.
- No edits to forbidden paths.
- No production destructive commands.
- Worker cannot publish; only Publisher can create PRs.

## Secret Handling

API keys belong in user-level env profiles or vendor auth files. They must not be written into repo files, artifacts, PR bodies, or logs.

## Dangerous Actions

The orchestrator blocks known dangerous command patterns before execution and checks changed files after execution. This two-step guard is stronger than prompt-only restrictions.

