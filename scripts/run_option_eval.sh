#!/usr/bin/env bash
# 全量期权评估：98 条，并发 15
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python scripts/langfuse_eval.py --limit 98 --concurrency 15 "$@"
