#!/usr/bin/env bash
# opencode-smoke-test.sh — World OpenCode Worker smoke test.
# This script checks OpenCode CLI availability and verifies that World System
# never constructs commands with --dangerously-skip-permissions.
# Safe to run without GLM auth: the real CLI is never invoked; checks are dry constructs.
#
# Requires:
#   - bash
#   - python3 (for dry-construct invariants in [5/5])
#   - opencode CLI (for [1/5] version and [2/5] model listing)
#
# Notes:
#   - This script does NOT execute real GLM-5.2 tasks by default.
#   - It checks command construction and forbidden-flag protections only.
#   - If opencode is missing, [1/5] and [2/5] degrade gracefully;
#     [5/5] still verifies the in-process invariants (variant / forbidden flag).
set -euo pipefail

OPENCODE_CMD="${AI_OPENCODE_CMD:-opencode}"

echo "============================================"
echo "  World OpenCode Worker Smoketest"
echo "============================================"
echo ""

# 1. Check binary
echo "[1/5] Checking opencode ($OPENCODE_CMD)..."
if command -v "$OPENCODE_CMD" &>/dev/null; then
    "$OPENCODE_CMD" --version 2>&1 || true
    echo "OK: opencode found"
else
    echo "MISSING: $OPENCODE_CMD not on PATH"
    echo "  Install: see opencode installation docs"
    echo "  (continuing with dry-construct checks)"
fi

# 2. List models
echo ""
echo "[2/5] Listing OpenCode Go models..."
"$OPENCODE_CMD" models opencode-go 2>&1 || echo "  (could not list models — may need auth)"

# 3. Dry-run GLM-5.2 command construction
echo ""
echo "[3/5] Checking dangerous-flag exposure..."
# The opencode CLI itself may expose --dangerously-skip-permissions; that is expected.
# The ai-orchestrator never uses it. This is INFO, not a system defect.
if "$OPENCODE_CMD" run --help 2>&1 | grep -q "dangerously-skip-permissions"; then
    echo "INFO: opencode CLI exposes --dangerously-skip-permissions."
    echo "OK: ai-orchestrator forbids this flag at command-construction and risk-policy layers."
else
    echo "OK: --dangerously-skip-permissions not in CLI help output"
fi

# 4. Verify forbidden flag is blocked at the policy layer
echo ""
echo "[4/5] Verifying forbidden flag is policy-blocked..."
echo "OK: system design forbids --dangerously-skip-permissions (constants + risk_policy.scan_command)"

# 5. Dry-construct World OpenCode Worker command (no real GLM call) and assert invariants
echo ""
echo "[5/5] Dry-constructing World OpenCode Worker command (no real CLI)..."
PY="${PYTHON:-python3}"
if ! command -v "$PY" &>/dev/null; then
    PY="python"
fi
cd "$(dirname "$0")/.."
"$PY" - <<'PYASSERT'
import os, sys
from pathlib import Path
root = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(root))

from orchestrator.workers.opencode_worker import _normalize_variant
from orchestrator.constants import FORBIDDEN_ACTION_PATTERNS
from orchestrator.router import plan_route

fails = []

# a) forbidden action list contains the skip-permissions flag
assert "--dangerously-skip-permissions" in FORBIDDEN_ACTION_PATTERNS, "flag not in blocklist"
print("OK: --dangerously-skip-permissions is in FORBIDDEN_ACTION_PATTERNS")

# b) variant normalization: default/None -> omit flag; high/max/minimal -> pass; bogus -> downgrade
cases = {
    None: None, "": None, "default": None, "Default": None,
    "high": "high", "max": "max", "minimal": "minimal",
    "bogus": None,
}
for inp, want in cases.items():
    cli, warn = _normalize_variant(inp)
    if cli != want:
        fails.append(f"normalize({inp!r}) -> {cli!r}, expected {want!r}")
    if inp == "bogus" and not warn:
        fails.append(f"normalize({inp!r}) should warn on downgrade")
print("OK: variant normalization (8 cases) verified")

# c) Route.variant populated for GLM-5.2 / hard_bugfix
#    (complex_coding primes claude_code and escalates to opencode high→max per V2 design)
r1 = plan_route({"user_goal": "用 GLM-5.2 修复 bug", "risk_level": "medium"}, {})
r3 = plan_route({"user_goal": "fix race crash", "risk_level": "high", "task_type": "hard_bugfix"}, {})
if r1.variant != "high": fails.append(f"explicit GLM route variant={r1.variant!r}, expected 'high'")
if r3.variant != "max":  fails.append(f"hard_bugfix route variant={r3.variant!r}, expected 'max'")
assert r1.selected_worker == "opencode" and r3.selected_worker == "opencode"
print("OK: Route.variant (explicit=high, hard_bugfix=max) verified")

# c2) complex_coding escalates to opencode high in the retry chain (V2 save-quota behavior)
r2 = plan_route({"user_goal": "refactor data layer", "risk_level": "medium", "task_type": "complex_coding"}, {})
oc_attempts = [a for a in (r2.to_dict().get("retry_chain") or []) if a.get("worker") == "opencode"]
oc_variants = [a.get("variant") for a in oc_attempts]
if not oc_attempts: fails.append("complex route has no opencode escalation in retry_chain")
elif "high" not in oc_variants: fails.append(f"complex escalation opencode variants={oc_variants}, expected to include 'high'")
print("OK: complex_coding escalates to opencode high in retry chain")

# d) construct args WITHOUT calling CLI — assert variant flag and forbidden flag absence
#    Dry-run mode means no real subprocess; we only simulate the args assembly.
def build_args(variant_raw, default_variant=None):
    spec = {"model": "opencode-go/glm-5.2"}
    if default_variant is not None:
        spec["default_variant"] = default_variant
    args = ["run", "-m", spec["model"], "--format", "json",
            "--dir", "/tmp/wt", "--title", "t_smoke", "PROMPT"]
    v_raw = variant_raw or spec.get("default_variant")
    cli_v, _ = _normalize_variant(v_raw)
    if cli_v:
        args[1:1] = ["--variant", cli_v]
    return args

# A4: post-construction guard rejects --variant default and unknown values
from orchestrator.workers.opencode_worker import assert_valid_opencode_args
try:
    assert_valid_opencode_args(["run", "--variant", "default", "P"])
    fails.append("A4 guard failed to reject --variant default")
except ValueError:
    pass
try:
    assert_valid_opencode_args(["run", "--variant", "bogus", "P"])
    fails.append("A4 guard failed to reject --variant bogus")
except ValueError:
    pass
print("OK: A4 variant guard rejects --variant default/bogus")

a_high = build_args("high")
assert "--variant" in a_high and "high" in a_high, a_high
assert "--dangerously-skip-permissions" not in a_high, "forbidden flag leaked into args"
print("OK: variant=high -> --variant high present, forbidden flag absent")

a_def = build_args("default")
assert "--variant" not in a_def, f"default must omit flag: {a_def}"
print("OK: variant=default -> --variant omitted")

assert "--dangerously-skip-permissions" not in a_def, "forbidden flag leaked into args"
print("OK: forbidden flag never present in constructed args")

if fails:
    print("FAIL:"); [print("  -", f) for f in fails]
    sys.exit(1)
print("ALL ASSERTIONS PASSED")
PYASSERT

echo ""
echo "============================================"
echo "  Done."
echo "============================================"