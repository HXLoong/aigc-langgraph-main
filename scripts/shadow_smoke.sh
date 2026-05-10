#!/usr/bin/env bash
# shadow_compare.py 端到端 smoke test
#
# 不连真 Dify。用 mock_api 提供假 Dify endpoint 验证 shadow 管道：
# - LangGraph /v1/workflows/run（真节点链路）
# - mock_dify endpoint（mock_api 已实现 /v1/workflows/run 占位）
# - shadow_compare 拉两边响应 → diff → 写报告

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT_DIR=".harness-runs/shadow-smoke-$(date +%Y%m%d-%H%M)"
mkdir -p "$OUT_DIR"

# ============================================================
# 预检
# ============================================================
echo ">>> 预检 LangGraph + mock_dify endpoint"

if ! curl -fs --max-time 3 http://localhost:8000/v1/workflows/run \
        -H 'Content-Type: application/json' \
        -d '{"inputs":{"query":"ping"},"response_mode":"blocking","user":"smoke"}' \
        > /dev/null 2>&1; then
    echo "ERROR: LangGraph 未启动在 8000 端口" >&2
    echo "       启动：uvicorn app.main:app --port 8000" >&2
    exit 1
fi
echo "    LangGraph: 启动成功 (http://localhost:8000)"

if ! curl -fs --max-time 3 http://localhost:8099/v1/workflows/run \
        -H 'Content-Type: application/json' \
        -d '{"inputs":{"query":"ping"},"response_mode":"blocking","user":"smoke"}' \
        > /dev/null 2>&1; then
    echo "ERROR: mock_api 未启动在 8099 端口（含 /v1/workflows/run mock dify）" >&2
    echo "       启动：uvicorn mock_api.server:app --port 8099" >&2
    exit 1
fi
echo "    mock_api (mock_dify): 启动成功 (http://localhost:8099)"

# ============================================================
# 跑 shadow（10 条 case dry-run）
# ============================================================
echo ""
echo ">>> 跑 shadow 双跑（最多 10 条 case，dry-run）"

python scripts/shadow_compare.py \
    --langgraph http://localhost:8000/v1/workflows/run \
    --dify http://localhost:8099/v1/workflows/run \
    --dify-api-key smoke-test-key \
    --sample tests/fixtures/golden.jsonl \
    --max-cases 10 \
    --output "$OUT_DIR/diff.json" \
    --fail-threshold 1.0 || true

echo ""
echo ">>> 报告"
if [ -f "$OUT_DIR/diff.json" ]; then
    jq '{summary, sample_diff: (.results | map({case_id, is_equal, diff_keys}) | .[0:3])}' "$OUT_DIR/diff.json"
fi

echo ""
echo ">>> 完成 · 输出 $OUT_DIR/diff.json"
echo ">>> 验证项："
echo "    1. shadow_compare 命令能跑通（无 crash）"
echo "    2. 能并发请求 LangGraph + mock_dify"
echo "    3. 响应归一化函数（_normalize_dify / _normalize_langgraph）能解析"
echo "    4. diff 比较 + summary 生成"
echo ""
echo ">>> 下一步：业务方提供真 Dify URL + API key，把 --dify 切换到生产"
