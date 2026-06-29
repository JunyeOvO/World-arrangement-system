from __future__ import annotations

from pathlib import Path

APP_NAME = "ai-orchestrator"
DEFAULT_HOME = Path.home() / ".ai-orchestrator"
DEFAULT_CLAUDE_CMD = "wsl -e claude"
DEFAULT_OPENCODE_CMD = "wsl -e opencode"

TERMINAL_STATES = {
    "COMPLETED",
    "COMPLETED_WITH_PATCH",
    "COMPLETED_NO_CHANGES",
    "COMPLETED_WITH_ARTIFACTS",
    "COMPLETED_WITH_PARTIAL_ARTIFACTS",
    "DRY_RUN_COMPLETED",
    "PR_CREATED",
    "FAILED_FINAL",
    "CANCELLED",
    "ROLLED_BACK",
}

# ── Category 1: Non-reversible commands → BLOCKED (input-side) ──
# These are commands that cause irreversible damage if executed,
# regardless of worktree isolation.
NON_REVERSIBLE_COMMAND_PATTERNS = [
    "git push --force",
    "rm -rf /",
    "rm -rf /*",
    "--dangerously-skip-permissions",
    "gh pr merge",
    "drop database",
    "truncate",
    "chmod -R 777 /",
    "curl * | sh",
    "wget * | sh",
]

# ── Category 2: Sensitive topic keywords → WARN only (input-side) ──
# These indicate tasks that touch sensitive areas, but the actual
# safety decision is made at the output gate (verify + review + no-auto-merge).
# Substring matching on these MUST use contextual matching to avoid false positives
# on words like "product" matching "prod".
SENSITIVE_TOPIC_KEYWORDS = [
    "auth",
    "authentication",
    "鉴权",
    "认证",
    "payment",
    "支付",
    "deploy",
    "部署",
    "security",
    "密码",
    "secret",
    "密钥",
    "credential",
    "password",
    "production",
    "生产",
    "database migration",
    "db migration",
    "数据迁移",
]

# ── Category 3: Forbidden write paths → BLOCKED (output-side) ──
# Writing to these paths is always blocked, even in an isolated worktree.
FORBIDDEN_WRITE_PATHS = [
    ".env",
    ".env.*",
    "secrets/**",
    "secrets.*",
    "keys/**",
    "keys.*",
    "credentials/**",
    "credentials.*",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/*.jks",
    "**/*.keystore",
]

# ── Category 4: Hard-approval write paths → HARD_APPROVAL (output-side) ──
# Writing to production infrastructure requires explicit user confirmation.
HARD_APPROVAL_WRITE_PATHS = [
    "infra/prod/**",
    "deploy/prod/**",
    "database/migrations/prod/**",
]

# ── Backward-compatibility aliases (do not remove) ──
# Existing code that references these will continue to work.
FORBIDDEN_ACTION_PATTERNS = NON_REVERSIBLE_COMMAND_PATTERNS

DEFAULT_FORBIDDEN_PATHS = [
    *FORBIDDEN_WRITE_PATHS,
    *HARD_APPROVAL_WRITE_PATHS,
    "firebase/**",
    "keystore/**",
    "signing/**",
]
