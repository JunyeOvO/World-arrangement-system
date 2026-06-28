#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-generic}"
GOAL="${2:-只读分析项目结构}"

cd "$(dirname "$0")/.."
uv run ai-dispatcher submit-task --project "$PROJECT" --goal "$GOAL" --dry-run

