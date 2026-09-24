#!/usr/bin/env bash
# 灰度上线 P0 应急回切脚本
#
# 触发场景：alerts.py 任一 P0 条件命中（is_canary=false 误切 / java_backend fail /
# 节点错误率失控 / LLM 失败率失控）→ on-call 决定回切到 Dify。
#
# 本脚本不切 Webhook（那是企微管理员人工操作）——它只负责服务侧的善后：
#   1. 备份 .env（带时间戳）
#   2. 提示并等待 Webhook 切回
#   3. 验证服务侧 canary_traffic 不再增长（30s 间隔取 2 次 baseline）
#   4. 注释掉 .env::CANARY_ROOM_IDS（避免重启后又认为该群是金丝雀）
#   5. 写 audit log → .rollback-audit.log（追加模式，留事故复盘证据）
#   6. 提示重启服务让 .env 生效（或 --auto-restart 直接重启）
#
# 跑法：
#   bash scripts/rollback_canary.sh --reason "java_backend fail at 22:14"
#   bash scripts/rollback_canary.sh --reason "..." --auto-restart -y
#   bash scripts/rollback_canary.sh --dry-run --reason "回切演练"
#
# 退出码：
#   0 成功
#   1 前置失败（.env 不存在 / CANARY_ROOM_IDS 已空）
#   2 metrics endpoint 不可达
#   3 用户取消
#   4 .env / audit log 写失败
#   5 重启失败

set -uo pipefail

# ============================================================
# 配置
# ============================================================
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env"
AUDIT_LOG="${PROJECT_DIR}/.rollback-audit.log"
METRICS_URL_DEFAULT="http://localhost:8000/metrics"
WAIT_SECONDS_DEFAULT=30
NON_CANARY_TOLERANCE_DEFAULT=5  # 30s 内 canary 流量增量超过此值 → 警告
PYTHON_BIN="${PYTHON_BIN:-python3}"

REASON=""
METRICS_URL="$METRICS_URL_DEFAULT"
WAIT_SECONDS="$WAIT_SECONDS_DEFAULT"
TOLERANCE="$NON_CANARY_TOLERANCE_DEFAULT"
AUTO_RESTART=0
SKIP_WAIT=0
ASSUME_YES=0
DRY_RUN=0

# ============================================================
# 输出工具
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()    { printf "${GREEN}✅%b${NC}\n" " $*"; }
info()  { printf "${BLUE}ℹ %b${NC}\n" " $*"; }
warn()  { printf "${YELLOW}⚠ %b${NC}\n" " $*"; }
fail()  { printf "${RED}❌%b${NC}\n" " $*"; }

section() {
    echo
    echo "=== $* ==="
}

abort() {
    fail "$1"
    [ -n "${2:-}" ] && echo "   → 详见: $2"
    exit "${3:-1}"
}

# ============================================================
# 参数解析
# ============================================================
print_help() {
    cat <<'EOF'
灰度上线 P0 应急回切脚本

用法：
  bash scripts/rollback_canary.sh --reason "<原因>" [选项]

必填参数：
  --reason "TEXT"          回切原因（写入 audit log，必填）

可选参数：
  --metrics-url URL        /metrics endpoint（默认 http://localhost:8000/metrics）
  --wait-seconds N         Webhook 切换后等待验证时长（默认 30）
  --tolerance N            canary 流量增量容忍阈值（默认 5）
  --auto-restart           回切完成后自动 systemctl restart otc-agent
  --skip-wait              跳过 30s 等待验证（已手工确认 Webhook 切干净）
  -y / --yes               所有交互问询都默认 yes（非交互模式）
  --dry-run                只显示，不改 .env / audit log
  -h / --help              本帮助

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reason) REASON="$2"; shift 2 ;;
        --metrics-url) METRICS_URL="$2"; shift 2 ;;
        --wait-seconds) WAIT_SECONDS="$2"; shift 2 ;;
        --tolerance) TOLERANCE="$2"; shift 2 ;;
        --auto-restart) AUTO_RESTART=1; shift ;;
        --skip-wait) SKIP_WAIT=1; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) print_help; exit 0 ;;
        *) abort "未知参数: $1（--help 查看用法）" ;;
    esac
done

if [ -z "$REASON" ]; then
    abort "--reason 必填（审计要求）。例：--reason \"java_backend fail at 22:14\"" \
        "docs/operations/on-call-runbook.md"
fi

# ============================================================
# 工具函数
# ============================================================

env_get() {
    local key="$1"
    [ ! -f "$ENV_FILE" ] && return
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-
}

confirm() {
    local prompt="$1"
    [ "$ASSUME_YES" = "1" ] && return 0
    read -r -p "$prompt [y/N] " ans
    [[ "$ans" =~ ^[yY]$ ]]
}

# 用 python 解析 prometheus 文本（避免 bash grep/awk 处理 label 脆弱）
parse_canary_counts() {
    local url="$1"
    "$PYTHON_BIN" - "$url" <<'PY' 2>&1
import sys
import urllib.request
import urllib.error

url = sys.argv[1]
try:
    req = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
except (urllib.error.URLError, OSError, TimeoutError) as exc:
    print(f"ERROR:{type(exc).__name__}:{exc}", file=sys.stderr)
    sys.exit(2)

canary = 0
non_canary = 0
for line in body.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if not line.startswith("otc_agent_canary_traffic_total"):
        continue
    try:
        _, rest = line.split("{", 1)
        labels_str, value_str = rest.split("}", 1)
        value = int(float(value_str.strip()))
    except (ValueError, IndexError):
        continue
    if 'is_canary="true"' in labels_str:
        canary += value
    elif 'is_canary="false"' in labels_str:
        non_canary += value

print(f"{canary} {non_canary}")
PY
}

# ============================================================
# Step 1 · 前置校验
# ============================================================
step1_preflight() {
    section "Step 1/6 · 前置校验"

    [ ! -f "$ENV_FILE" ] && abort ".env 不存在: $ENV_FILE"

    local canary_val
    canary_val=$(env_get "CANARY_ROOM_IDS")
    if [ -z "$canary_val" ]; then
        warn "CANARY_ROOM_IDS 已为空 —— 服务侧无需回切"
        info "（如果只是想确保 .env 干净，可加 --dry-run 检查；本脚本现在退出）"
        exit 1
    fi

    info "当前 CANARY_ROOM_IDS = $canary_val"
    info "回切原因: $REASON"
    [ "$DRY_RUN" = "1" ] && warn "DRY-RUN 模式：不会改 .env / audit log"

    if ! confirm "确认要执行 应急回切吗？"; then
        warn "用户取消"
        exit 3
    fi
    ok "前置校验通过"
}

# ============================================================
# Step 2 · 备份 .env
# ============================================================
step2_backup_env() {
    section "Step 2/6 · 备份 .env"

    local ts backup_file
    ts="$(date '+%Y%m%d-%H%M%S')"
    backup_file="${ENV_FILE}.rollback-${ts}"

    if [ "$DRY_RUN" = "1" ]; then
        warn "DRY-RUN：将备份到 ${backup_file}（实际未写）"
        ENV_BACKUP_FILE="$backup_file"
        return
    fi

    cp -p "$ENV_FILE" "$backup_file" || abort ".env 备份失败" "" 4
    chmod 600 "$backup_file" 2>/dev/null || true
    ok "已备份 → $backup_file"
    ENV_BACKUP_FILE="$backup_file"
}

# ============================================================
# Step 3 · 取 baseline canary 流量
# ============================================================
step3_baseline_metrics() {
    section "Step 3/6 · 取 baseline canary 流量"

    local result
    result=$(parse_canary_counts "$METRICS_URL" 2>&1)
    local rc=$?
    if [ $rc -ne 0 ]; then
        warn "metrics endpoint 不可达 ($METRICS_URL): $result"
        warn "  → 跳过 baseline 校验。服务可能已挂——优先关注 Webhook 切回完成度"
        BASELINE_CANARY=-1
        BASELINE_NON_CANARY=-1
        return
    fi

    BASELINE_CANARY=$(echo "$result" | awk '{print $1}')
    BASELINE_NON_CANARY=$(echo "$result" | awk '{print $2}')
    info "baseline · is_canary=true:  $BASELINE_CANARY"
    info "baseline · is_canary=false: $BASELINE_NON_CANARY"
    if [ "$BASELINE_NON_CANARY" -gt 0 ] 2>/dev/null; then
        warn "is_canary=false > 0 —— 这正是 P0 告警的根因，回切后这条线应当停止增长"
    fi
}

# ============================================================
# Step 4 · 提示 Webhook 切回 + 等待验证
# ============================================================
step4_wait_webhook() {
    section "Step 4/6 · 等待企微 Webhook 切回 Dify"

    cat <<EOF

  ┌─────────────────────────────────────────────────────────────┐
  │ 请企微管理员现在执行：                                       │
  │                                                              │
  │   把白名单群的群机器人 Webhook 从 LangGraph 切回 Dify。      │
  │   涉及群（来自 CANARY_ROOM_IDS）：                           │
  │     $(env_get CANARY_ROOM_IDS)
  │                                                              │
  │ 完成后回车继续（本脚本会等 ${WAIT_SECONDS}s 验证流量已停）。  │
  └─────────────────────────────────────────────────────────────┘

EOF

    if [ "$ASSUME_YES" = "0" ]; then
        read -r -p "Webhook 已切回？回车继续验证..." _ans
    fi

    if [ "$SKIP_WAIT" = "1" ]; then
        warn "--skip-wait 跳过 ${WAIT_SECONDS}s 流量校验"
        return
    fi

    if [ "$BASELINE_CANARY" = "-1" ]; then
        warn "baseline 不可用 —— 跳过流量校验"
        return
    fi

    info "等待 ${WAIT_SECONDS}s 后再取一次 canary 计数..."
    sleep "$WAIT_SECONDS"

    local result canary_after non_canary_after delta_canary
    result=$(parse_canary_counts "$METRICS_URL" 2>&1)
    if [ $? -ne 0 ]; then
        warn "metrics endpoint 第二次不可达: $result"
        warn "  → 跳过校验，继续后续步骤"
        return
    fi
    canary_after=$(echo "$result" | awk '{print $1}')
    non_canary_after=$(echo "$result" | awk '{print $2}')
    delta_canary=$(( canary_after - BASELINE_CANARY ))

    info "${WAIT_SECONDS}s 后 · is_canary=true:  $canary_after (Δ=$delta_canary)"
    info "${WAIT_SECONDS}s 后 · is_canary=false: $non_canary_after"

    if [ "$delta_canary" -gt "$TOLERANCE" ]; then
        warn "canary 流量在 ${WAIT_SECONDS}s 内增长 ${delta_canary}（> 容忍 ${TOLERANCE}）"
        warn "  → Webhook 可能没切干净！请企微管理员复查白名单群的 Webhook 配置"
        if ! confirm "已知风险，继续清空 .env CANARY_ROOM_IDS？"; then
            warn "用户中止 —— .env 未改动，audit log 未写"
            exit 3
        fi
    else
        ok "canary 流量已停（${WAIT_SECONDS}s 内 Δ=${delta_canary} ≤ ${TOLERANCE}）"
    fi
}

# ============================================================
# Step 5 · 注释掉 .env::CANARY_ROOM_IDS
# ============================================================
step5_disable_canary() {
    section "Step 5/6 · 注释 .env::CANARY_ROOM_IDS"

    local original_val ts
    original_val=$(env_get "CANARY_ROOM_IDS")
    ts="$(date '+%Y-%m-%d %H:%M:%S')"

    if [ "$DRY_RUN" = "1" ]; then
        warn "DRY-RUN：将注释掉 CANARY_ROOM_IDS（原值: ${original_val}）"
        return
    fi

    # 用 awk 替换：
    # 1. 原行变成注释（保留历史值供事后查阅）
    # 2. 紧跟一行新的空值（让重启后真正生效）
    local tmp="${ENV_FILE}.tmp.$$"
    awk -v orig="$original_val" -v ts="$ts" -v reason="$REASON" '
        /^CANARY_ROOM_IDS=/ {
            print "# 应急回切 " ts " · 原值=" orig " · 原因=" reason
            print "# " $0
            print "CANARY_ROOM_IDS="
            next
        }
        { print }
    ' "$ENV_FILE" > "$tmp"

    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        abort ".env 改写失败（awk 输出空）" "" 4
    fi

    mv "$tmp" "$ENV_FILE" || abort ".env 替换失败" "" 4
    chmod 600 "$ENV_FILE" 2>/dev/null || true

    ok "CANARY_ROOM_IDS 已清空（原值已注释保留供查阅）"
}

# ============================================================
# Step 6 · 写 audit log
# ============================================================
step6_audit_log() {
    section "Step 6/6 · 写 audit log"

    local ts user host original_val
    ts="$(date '+%Y-%m-%d %H:%M:%S %Z')"
    user="${USER:-unknown}"
    host="$(hostname)"
    original_val="$(grep -E '^# CANARY_ROOM_IDS=' "$ENV_FILE" 2>/dev/null | tail -1 | sed 's/^# //')"

    if [ "$DRY_RUN" = "1" ]; then
        warn "DRY-RUN：audit log 未写"
        return
    fi

    {
        echo "----------------------------------------"
        echo "rollback_at: $ts"
        echo "operator:    $user@$host"
        echo "reason:      $REASON"
        echo "env_backup:  ${ENV_BACKUP_FILE:-<not_backed_up>}"
        echo "before:      $original_val"
        echo "after:       CANARY_ROOM_IDS="
        echo "metrics_baseline_canary:  ${BASELINE_CANARY}"
        echo "metrics_baseline_non_canary: ${BASELINE_NON_CANARY}"
    } >> "$AUDIT_LOG" || abort "audit log 写失败: $AUDIT_LOG" "" 4

    chmod 600 "$AUDIT_LOG" 2>/dev/null || true
    ok "audit log 追加 → $AUDIT_LOG"
}

# ============================================================
# 重启 + 完成
# ============================================================
maybe_restart() {
    if [ "$AUTO_RESTART" = "0" ]; then
        echo
        info "下一步：重启 otc-agent 让 .env 新值生效"
        info "  · systemd: sudo systemctl restart otc-agent"
        info "  · docker:  docker compose -f infra/.../docker-compose.yml restart"
        info "  · 直接进程: kill \$(cat app.pid) && nohup uvicorn ... &"
        return
    fi

    section "重启服务"
    if [ "$DRY_RUN" = "1" ]; then
        warn "DRY-RUN：跳过 systemctl restart"
        return
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        warn "未安装 systemctl —— 跳过自动重启，请手工 kill+启动"
        return
    fi
    info "执行: sudo systemctl restart otc-agent"
    if sudo systemctl restart otc-agent; then
        ok "otc-agent 已重启"
    else
        fail "systemctl restart 失败"
        exit 5
    fi
}

print_summary() {
    section "回切完成"
    cat <<EOF

  rollback_at: $(date '+%Y-%m-%d %H:%M:%S')
  reason:      $REASON
  env_backup:  ${ENV_BACKUP_FILE:-<dry-run>}
  audit_log:   $AUDIT_LOG

  事故复盘清单：
    1. metrics_snapshot.py 拍快照保留事故现场（保留 7 天）
    2. 在 docs/incidents/ 写 postmortem
    3. 如果是上游故障：联系 java_backend 团队 / Qwen API 厂商
    4. 修复后重新走切流流程，CANARY_ROOM_IDS 从 .env 注释中恢复（核对回切原值）

EOF
}

# ============================================================
# 主流程
# ============================================================
main() {
    section "灰度上线应急回切"
    info "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    info "脚本: $0"
    info "原因: $REASON"

    step1_preflight
    step2_backup_env
    step3_baseline_metrics
    step4_wait_webhook
    step5_disable_canary
    step6_audit_log
    maybe_restart
    print_summary
}

main
