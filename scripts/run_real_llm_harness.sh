#!/usr/bin/env bash
# 真 LLM 跑 Harness 三阶段 wrapper
# 用法：bash scripts/run_real_llm_harness.sh [stage]
#   stage 可选：anchor | seeds | canary | all（默认 all）
#
# 文档：docs/m2-real-llm-run-guide.md

set -euo pipefail

STAGE="${1:-all}"
TS=$(date +"%Y%m%d-%H%M")
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ============================================================
# 预检
# ============================================================
preflight() {
    echo ">>> 预检环境"

    # .env 检查
    if [ ! -f ".env" ]; then
        echo "ERROR: .env 缺失，复制 .env.example 并填实际 key" >&2
        exit 1
    fi
    if ! grep -q "^QWEN_API_KEY=" .env || grep -q "^QWEN_API_KEY=your-qwen-api-key" .env; then
        echo "ERROR: .env 中 QWEN_API_KEY 未配置实际值" >&2
        exit 1
    fi
    echo "    .env OK"

    # mock_api 健康检查（端口 8099）
    local mock_url="http://localhost:8099/admin-api/integration/securities-instrument/select?keyword=test"
    if ! curl -fs --max-time 3 "$mock_url" > /dev/null 2>&1; then
        echo "ERROR: mock_api 未启动（http://localhost:8099 不通）" >&2
        echo "       请在另一终端运行：" >&2
        echo "         uvicorn mock_api.server:app --port 8099" >&2
        echo "       或后台：" >&2
        echo "         nohup uvicorn mock_api.server:app --port 8099 > /tmp/mock_api.log 2>&1 &" >&2
        exit 1
    fi
    echo "    mock_api OK (http://localhost:8099)"

    # LLM 连通性
    echo "    LLM 连通性测试 ..."
    python -c "
import asyncio
from app.llm.clients import get_qwen_structured
from pydantic import BaseModel

class Out(BaseModel):
    type: str

async def main():
    llm = get_qwen_structured().with_structured_output(Out)
    r = await llm.ainvoke([('user', '请输出 JSON: {\"type\": \"ping\"}')])
    print(f'    Qwen OK: {r}')

asyncio.run(main())
" || { echo "ERROR: LLM 连通性失败" >&2; exit 2; }
}

# ============================================================
# 阶段 A：锚点烟测（30 条 / ~3min / ~¥0.5）
# ============================================================
run_anchor() {
    local out=".harness-runs/${TS}-anchor"
    echo ""
    echo ">>> 阶段 A · 锚点烟测（30 条）"
    echo "    输出：$out"
    for cat in swap option option_close; do
        echo "    --- $cat ---"
        python -m harness run --category "$cat" --out "$out/$cat" || true
    done
    echo ""
    echo ">>> 阶段 A 报告："
    for cat in swap option option_close; do
        if [ -f "$out/$cat/summary.json" ]; then
            jq -r '"  \(.passed)/\(.total) PASS (\(.pass_rate * 100 | floor)%)  '"$cat"'"' "$out/$cat/summary.json"
        fi
    done
}

# ============================================================
# 阶段 B：业务种子全集（287 条 / ~25min / ~¥4-5）
# ============================================================
run_seeds() {
    local out=".harness-runs/${TS}-seeds"
    echo ""
    echo ">>> 阶段 B · 业务种子全集（317 条）"
    echo "    输出：$out"
    python -m harness run --out "$out"
    echo ""
    echo ">>> 阶段 B 报告："
    jq -r '"  总: \(.passed)/\(.total) PASS (\(.pass_rate * 100 | floor)%)"' "$out/summary.json"
    echo "    详细见 $out/summary.md"
}

# ============================================================
# 阶段 C：v1/v2 灰度对比（强制 50/50 各跑一次 / ~50min / ~¥10）
# ============================================================
run_canary() {
    local out_v1=".harness-runs/${TS}-v1-control"
    local out_v2=".harness-runs/${TS}-v2-canary"
    echo ""
    echo ">>> 阶段 C · v1/v2 灰度对比"
    echo "    控制组（全 v1）：$out_v1"
    OTC_PROMPT_SWAP_INTENT_VERSION=v1 python -m harness run --category swap --out "$out_v1"

    echo "    实验组（全 v2）：$out_v2"
    OTC_PROMPT_SWAP_INTENT_VERSION=v2 python -m harness run --category swap --out "$out_v2"

    echo ""
    echo ">>> v1/v2 对比："
    pass_v1=$(jq -r '.pass_rate' "$out_v1/summary.json")
    pass_v2=$(jq -r '.pass_rate' "$out_v2/summary.json")
    echo "    swap PASS · v1=${pass_v1} · v2=${pass_v2}"
    echo "    完整对比："
    diff <(jq -S '.by_category, .pass_rate' "$out_v1/summary.json") \
         <(jq -S '.by_category, .pass_rate' "$out_v2/summary.json") || true
}

# ============================================================
# main
# ============================================================
preflight

case "$STAGE" in
    anchor)  run_anchor ;;
    seeds)   run_seeds ;;
    canary)  run_canary ;;
    all)     run_anchor; run_seeds; run_canary ;;
    *)       echo "ERROR: stage must be one of: anchor | seeds | canary | all" >&2; exit 1 ;;
esac

echo ""
echo ">>> 全部完成 · 报告目录 .harness-runs/${TS}-*"
echo ">>> 文档：docs/m2-real-llm-run-guide.md"
