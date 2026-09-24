#!/usr/bin/env bash
# 回切演练 smoke 脚本 · 不注入故障，仅串联 5 件套验证可用性。
#
# 用途：
#   1. 首次 walkthrough docs/operations/on-call-runbook.md §8 回切演练前，本地干跑确认
#      5 件套工具的命令、退出码、输出格式都正常。
#   2. 演练当天 Scene 1（基线确认）可直接调本脚本替代手敲多条命令。
#
# 注意：
#   - 本脚本只覆盖 Scene 1（基线）+ Scene 5 的查询动作（不真回切）+
#     Scene 6 的恢复验证（不真改 .env）。
#   - **绝不**注入故障 / 改 .env / 调 rollback。真演练按 docs/operations/on-call-runbook.md §8 人工执行。
#
# 跑法：
#   bash scripts/drill_smoke.sh                                # 本地（默认 :8000）
#   bash scripts/drill_smoke.sh --metrics-url http://prod:8000/metrics
#   bash scripts/drill_smoke.sh --skip-deploy-check            # 略过 deploy 脚本检查
#   bash scripts/drill_smoke.sh --json                         # 输出汇总 JSON
#
# 退出码：
#   0 所有检查通过 → 可演练
#   1 至少一项 ❌ → 演练取消，先修基线
#   2 .env / 工具 / 服务不可达 → 环境未就绪

set -uo pipefail

# ============================================================
# 配置
# ============================================================
# PROJECT_DIR 默认推断为脚本所在目录的父目录；
# 环境变量 PROJECT_DIR 可显式覆盖（测试用 / 跨项目复用）。
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
METRICS_URL_DEFAULT="http://localhost:8000/metrics"
READY_URL_DEFAULT="http://localhost:8000/ready"

METRICS_URL="$METRICS_URL_DEFAULT"
READY_URL="$READY_URL_DEFAULT"
SKIP_DEPLOY=0
JSON_OUTPUT=0
PYTHON_BIN="${PYTHON_BIN:-python3}"

# 检查结果累计
TOTAL=0
PASSED=0
FAILED=0
declare -a CHECK_RESULTS  # "name|status|detail"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================================
# 输出工具
# ============================================================
section() { echo; echo "=== $* ==="; }

record_check() {
    local name="$1" status="$2" detail="${3:-}"
    TOTAL=$((TOTAL + 1))
    case "$status" in
        pass)
            PASSED=$((PASSED + 1))
            printf "${GREEN}✅ %s${NC}\n" "$name"
            [ -n "$detail" ] && printf "    ${BLUE}%s${NC}\n" "$detail"
            ;;
        fail)
            FAILED=$((FAILED + 1))
            printf "${RED}❌ %s${NC}\n" "$name"
            [ -n "$detail" ] && printf "    ${RED}%s${NC}\n" "$detail"
            ;;
        warn)
            printf "${YELLOW}⚠  %s${NC}\n" "$name"
            [ -n "$detail" ] && printf "    ${YELLOW}%s${NC}\n" "$detail"
            ;;
    esac
    CHECK_RESULTS+=("${name}|${status}|${detail}")
}

# ============================================================
# 参数解析
# ============================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --metrics-url) METRICS_URL="$2"; shift 2 ;;
        --ready-url) READY_URL="$2"; shift 2 ;;
        --skip-deploy-check) SKIP_DEPLOY=1; shift ;;
        --json) JSON_OUTPUT=1; shift ;;
        -h|--help)
            cat <<'EOF'
回切演练 smoke 脚本

用法：bash scripts/drill_smoke.sh [选项]

选项：
  --metrics-url URL        默认 http://localhost:8000/metrics
  --ready-url URL          默认 http://localhost:8000/ready
  --skip-deploy-check      略过 deploy-customer.sh 调用（本地无 .env 时用）
  --json                   末尾追加机器可读 JSON 汇总
  -h, --help               本帮助

退出码：0=可演练 / 1=有 ❌ / 2=环境未就绪
EOF
            exit 0
            ;;
        *) echo "未知参数: $1（--help 查看用法）" >&2; exit 2 ;;
    esac
done

# ============================================================
# Check 1 · 演练 5 件套工具存在
# ============================================================
check_tools_exist() {
    section "Check 1/6 · 5 件套工具就位"
    local tools=(
        "scripts/canary_status.py"
        "scripts/metrics_snapshot.py"
        "scripts/deploy-customer.sh"
        "scripts/rollback_canary.sh"
        "infra/grafana/dashboards/otc-agent-overview.json"
    )
    local missing=()
    for t in "${tools[@]}"; do
        if [ ! -f "${PROJECT_DIR}/$t" ]; then
            missing+=("$t")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_check "5 件套工具存在" pass "全部 ${#tools[@]} 项"
    else
        record_check "5 件套工具存在" fail "缺失: ${missing[*]}"
    fi
}

# ============================================================
# Check 2 · 工具语法 OK（bash -n / python --help 可加载）
# ============================================================
check_tools_syntax() {
    section "Check 2/6 · 工具语法可加载"
    local shells=(
        "scripts/deploy-customer.sh"
        "scripts/rollback_canary.sh"
    )
    local pyscripts=(
        "scripts/canary_status.py"
        "scripts/metrics_snapshot.py"
    )

    local errs=()
    for s in "${shells[@]}"; do
        local f="${PROJECT_DIR}/$s"
        [ ! -f "$f" ] && continue
        if ! bash -n "$f" 2>/dev/null; then
            errs+=("$s [bash syntax]")
        fi
    done
    for s in "${pyscripts[@]}"; do
        local f="${PROJECT_DIR}/$s"
        [ ! -f "$f" ] && continue
        # 真正执行 --help：ast.parse 会放过导入即 NameError 的合并遗留
        if ! "$PYTHON_BIN" "$f" --help >/dev/null 2>&1; then
            errs+=("$s [py load]")
        fi
    done

    if [ "${#errs[@]}" -eq 0 ]; then
        record_check "工具语法可加载" pass "shells×${#shells[@]} + py×${#pyscripts[@]}"
    else
        record_check "工具语法可加载" fail "${errs[*]}"
    fi
}

# ============================================================
# Check 3 · /ready 4 上游全绿
# ============================================================
check_ready() {
    section "Check 3/6 · /ready 4 上游探测"
    local tmp status
    tmp=$(mktemp)
    status=$(curl -s -m 10 -o "$tmp" -w '%{http_code}' "$READY_URL" 2>/dev/null)
    case "$status" in
        200)
            record_check "/ready 200" pass "4 个上游全绿"
            ;;
        503)
            local checks
            checks=$(head -c 200 "$tmp" 2>/dev/null)
            record_check "/ready 503 degraded" fail "checks: $checks"
            ;;
        000|"")
            record_check "/ready 不可达" fail "服务未启动或 URL 错: $READY_URL"
            ;;
        *)
            record_check "/ready HTTP $status" fail "意外状态码（/ready 路由可能未注册）"
            ;;
    esac
    rm -f "$tmp"
}

# ============================================================
# Check 4 · metrics_snapshot 可跑且无关键错
# ============================================================
check_metrics_snapshot() {
    section "Check 4/6 · metrics_snapshot.py 可跑"
    local out rc
    out=$("$PYTHON_BIN" "${PROJECT_DIR}/scripts/metrics_snapshot.py" --url "$METRICS_URL" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        record_check "metrics_snapshot 退出码" fail "exit=$rc · $(echo "$out" | head -2 | tr '\n' '|')"
        return
    fi
    if echo "$out" | grep -qE "节点级|业务指标|金丝雀|健康检查"; then
        local node_warn business_warn canary_warn
        node_warn=$(echo "$out" | grep -c "⚠️" || true)
        canary_warn=$(echo "$out" | grep -c "❌" || true)
        local detail="4 段输出齐全"
        [ "$node_warn" != "0" ] && detail+="  ⚠️×${node_warn}"
        [ "$canary_warn" != "0" ] && detail+="  ❌×${canary_warn}"
        record_check "metrics_snapshot 输出" pass "$detail"
    else
        record_check "metrics_snapshot 输出" fail "缺少预期段（解析失败？）"
    fi
}

# ============================================================
# Check 5 · canary_status 状态可读
# ============================================================
check_canary_status() {
    section "Check 5/6 · canary_status.py 状态"
    local out rc
    out=$("$PYTHON_BIN" "${PROJECT_DIR}/scripts/canary_status.py" --url "$METRICS_URL" 2>&1)
    rc=$?
    # canary_status 退出码 0=正常 1=is_breach 2=metrics 不可达
    case "$rc" in
        0)
            local mode_line
            mode_line=$(echo "$out" | grep -E "模式|allowlist|未启用|白名单|ALL" | head -1)
            record_check "canary_status 状态" pass "$mode_line"
            ;;
        1)
            record_check "canary_status breach" fail "is_canary=false > 0 · 检查 CANARY_ROOM_IDS"
            ;;
        2)
            record_check "canary_status metrics 不可达" fail "URL: $METRICS_URL"
            ;;
        *)
            record_check "canary_status 退出码异常" fail "exit=$rc · $(echo "$out" | head -2 | tr '\n' '|')"
            ;;
    esac
}

# ============================================================
# Check 6 · deploy-customer.sh step 2 + 9 可单跑
# ============================================================
check_deploy_steps() {
    section "Check 6/6 · deploy-customer.sh --only 2/9"
    if [ "$SKIP_DEPLOY" = "1" ]; then
        record_check "deploy 检查" warn "用户用 --skip-deploy-check 跳过"
        return
    fi
    if [ ! -f "${PROJECT_DIR}/.env" ]; then
        record_check "deploy step 2" warn ".env 不存在 → 跳过（演练前 24h 清单 §3.1）"
        return
    fi

    local out rc
    out=$(cd "$PROJECT_DIR" && bash scripts/deploy-customer.sh --only 2 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ] && echo "$out" | grep -q "必填字段全部就绪"; then
        local canary_line
        canary_line=$(echo "$out" | grep -E "金丝雀" | head -1 | sed 's/^.*[FW] //')
        record_check "deploy step 2 (.env 校验)" pass "$canary_line"
    else
        record_check "deploy step 2 (.env 校验)" fail "exit=$rc · $(echo "$out" | tail -2 | tr '\n' '|')"
        return
    fi

    out=$(cd "$PROJECT_DIR" && bash scripts/deploy-customer.sh --only 9 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ] && echo "$out" | grep -qE "/health 200|GET /ready 200"; then
        record_check "deploy step 9 (健康检查)" pass "/health + /ready 200"
    elif echo "$out" | grep -q "/ready 503"; then
        record_check "deploy step 9" fail "/ready 503 degraded"
    else
        record_check "deploy step 9" fail "exit=$rc · $(echo "$out" | tail -2 | tr '\n' '|')"
    fi
}

# ============================================================
# 汇总输出
# ============================================================
print_summary() {
    section "汇总"
    local rate
    if [ "$TOTAL" -gt 0 ]; then
        rate=$(awk -v p="$PASSED" -v t="$TOTAL" 'BEGIN {printf "%.0f", p/t*100}')
    else
        rate=0
    fi
    printf "  通过: ${GREEN}%d${NC}  失败: ${RED}%d${NC}  总数: %d  (通过率 %d%%)\n\n" \
        "$PASSED" "$FAILED" "$TOTAL" "$rate"

    if [ "$FAILED" -eq 0 ]; then
        printf "${GREEN}=== 演练基线 OK · 可执行 docs/operations/on-call-runbook.md §8 回切演练 ===${NC}\n"
        return 0
    fi
    printf "${RED}=== 演练基线异常 · 修复后再演练 ===${NC}\n"
    echo "  失败项："
    for line in "${CHECK_RESULTS[@]}"; do
        IFS='|' read -r name st detail <<<"$line"
        [ "$st" = "fail" ] && echo "    · $name${detail:+ — $detail}"
    done
    return 1
}

json_escape() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//$'\n'/\\n}
    value=${value//$'\r'/\\r}
    value=${value//$'\t'/\\t}
    printf '%s' "$value"
}

print_json() {
    [ "$JSON_OUTPUT" = "0" ] && return
    echo
    echo "{"
    echo "  \"timestamp\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\","
    echo "  \"total\": $TOTAL,"
    echo "  \"passed\": $PASSED,"
    echo "  \"failed\": $FAILED,"
    echo "  \"checks\": ["
    local i first=1
    for line in "${CHECK_RESULTS[@]}"; do
        IFS='|' read -r name st detail <<<"$line"
        [ "$first" = "1" ] && first=0 || echo ","
        local name_e detail_e
        name_e=$(json_escape "$name")
        detail_e=$(json_escape "$detail")
        printf '    {"name": "%s", "status": "%s", "detail": "%s"}' \
            "$name_e" "$st" "$detail_e"
    done
    echo
    echo "  ]"
    echo "}"
}

# ============================================================
# 主流程
# ============================================================
section "回切演练 smoke · $(date '+%Y-%m-%d %H:%M:%S')"
echo "  PROJECT_DIR: $PROJECT_DIR"
echo "  METRICS_URL: $METRICS_URL"
echo "  READY_URL:   $READY_URL"

check_tools_exist
check_tools_syntax
check_ready
check_metrics_snapshot
check_canary_status
check_deploy_steps

print_summary
summary_rc=$?
print_json
exit $summary_rc
