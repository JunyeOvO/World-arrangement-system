# World Verifier Permission Guard

World verifier commands now use the same static worker permission model as
worker launch and write-path checks.

## Why

Project `test_commands` and `build_commands` are configuration data. They must
not bypass the worker permission profile simply because they run after the
worker returns.

This closes the gap where a dangerous command could be stored as a verification
command and then run by `subprocess.run(..., shell=True)`.

## Behavior

When `permission_worker` is provided to `verify(...)`:

- commands matching `bash.allow` run normally
- commands matching `bash.ask` do not run automatically
- commands matching `bash.deny` do not run
- commands outside the allow list do not run

Blocked commands are still written to the verify log and `verify.json` as
structured `CommandResult` rows.

Return codes:

- `125`: command requires explicit ask/approval
- `126`: command denied by the static permission profile

`VerifyResult.forbidden_allowed` is false when any verification command is
blocked or requires ask. It is also false when changed files touch forbidden
paths.

## Allowed Safe Commands

The default profiles allow common test/build commands, including:

- `pytest*`
- `python -m pytest*`
- `uv run pytest*`
- `npm test*`
- `npm.cmd test*`
- `pnpm test*`
- `pnpm.cmd test*`
- `npm run build*`
- `npm.cmd run build*`
- `pnpm build*`

Install, dependency mutation, push, merge, production deployment, destructive
filesystem, and permission-bypass commands remain blocked or require ask.

## Trust Boundary

The verifier still runs project commands in the isolated task worktree. This
guard only determines whether the command is allowed to start. It does not make
arbitrary project scripts safe, so production deploy, secret access, remote
push, and dependency mutation stay outside automatic execution.
