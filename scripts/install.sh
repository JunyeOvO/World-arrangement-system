#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
uv sync --all-extras --dev
mkdir -p "${AI_ORCHESTRATOR_HOME:-$HOME/.ai-orchestrator}/runs"

echo "Installed ai-orchestrator-v1."
echo "Copy config/*.example into ${AI_ORCHESTRATOR_HOME:-$HOME/.ai-orchestrator}/ and edit repo paths/API profiles."
