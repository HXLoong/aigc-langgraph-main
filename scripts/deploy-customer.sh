#!/usr/bin/env bash
# ============================================================
# otc-agent 客户现场一键部署脚本（C1.13 / Issue #58）
#
# 用法：
#   bash scripts/deploy-customer.sh             # 顺序跑全部步骤
#   bash scripts/deploy-customer.sh --step 5    # 从第 5 步开始（断点续传）
#   bash scripts/deploy-customer.sh --only 7    # 只跑第 7 步
#   bash scripts/deploy-customer.sh --dry-run   # 验证前置条件，不实际改动
#
# 10 步流程：
#   1. 前置检查（OS / Docker / Python / 内存 / 磁盘）
#   2. .env 校验（必填字段全有）
#   3. MySQL 连通 + 版本（ADR 0009 8.0.19 ≤ v < 9.6.0）
#   4. Java 后端连通（至少 1 个 read endpoint 返回 CommonResult）
#   5. LangFuse 启动（docker compose up + 等 5 容器 healthy）
#   6. LangFuse 项目 + Key 提示（人工创建后填回 .env）
#   7. 应用 Python 依赖（pip 或离线 wheel）
#   8. 应用启动（uvicorn，可后台）
#   9. 健康检查（/health 返回 200）
#  10. Smoke 自检（3 条已知 case）
#
# 每步独立 function，失败时打印诊断 + 文档链接，并不向下跑。
# 幂等：重复跑不破坏现有部署，已 OK 的步骤打印 "✅ 已就绪" 跳过。
#
# 关联文档：
#   - docs/deploy/customer-private.md（详细手工步骤）
#   - docs/deploy/langfuse-self-hosted.md（LangFuse 深度部署）
#   - docs/customer/customer-env-assessment.md（环境调研）
#   - docs/on-call-runbook.md（部署后故障）
# ============================================================

set -u  # 未定义变量报错；不用 -e，每步函数自己控制 exit

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_DIR}/.env"
LANGFUSE_DIR="${PROJECT_DIR}/infra/langfuse"
LOG_FILE="${PROJECT_DIR}/deploy-customer.log"

# ---- 颜色（无 tty 时禁用）----
if [ -t 1 ]; then
    BOLD=$(tput bold); RED=$(tput setaf 1); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); BLUE=$(tput setaf 4); RESET=$(tput sgr0)
else
    BOLD=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi

# ---- 参数解析 ----
START_STEP=1
ONLY_STEP=""
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --step) START_STEP="$2"; shift 2 ;;
        --only) ONLY_STEP="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help)
            grep "^#" "$0" | head -50
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

# ---- 工具函数 ----
log()  { echo "$(date '+%F %T') $*" | tee -a "$LOG_FILE"; }
info() { echo "${BLUE}ℹ${RESET}  $*"; log "[INFO] $*"; }
ok()   { echo "${GREEN}✅${RESET} $*"; log "[OK] $*"; }
warn() { echo "${YELLOW}⚠${RESET}  $*"; log "[WARN] $*"; }
fail() { echo "${RED}❌${RESET} $*"; log "[FAIL] $*"; }
section() { echo; echo "${BOLD}=== $* ===${RESET}"; log "===== $* ====="; }

# 提示并退出（含文档链接）
abort() {
    local msg="$1"
    local doc="${2:-docs/on-call-runbook.md}"
    fail "$msg"
    echo "   📖 排查参考：${doc}"
    echo "   📖 完整手工部署：docs/deploy/customer-private.md"
    exit 1
}

# 读 .env 中变量值
env_get() {
    local key="$1"
    grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | sed 's/^"\(.*\)"$/\1/' | sed "s/^'\(.*\)'$/\1/"
}

# 是否应该跑这一步
should_run_step() {
    local n="$1"
    [ -n "$ONLY_STEP" ] && { [ "$ONLY_STEP" = "$n" ] && return 0 || return 1; }
    [ "$n" -ge "$START_STEP" ] && return 0 || return 1
}

# ============================================================
# Step 1 · 前置检查
# ============================================================
step1_preflight() {
    section "Step 1/10 · 前置检查"

    # OS
    info "OS: $(uname -s)"

    # Docker
    if ! command -v docker >/dev/null 2>&1; then
        abort "未安装 Docker (≥ 24.x)" "docs/customer/customer-env-assessment.md#2.2"
    fi
    local docker_ver
    docker_ver=$(docker --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
    info "Docker: $docker_ver"

    # Docker Compose
    if ! docker compose version >/dev/null 2>&1; then
        abort "未安装 Docker Compose v2 (plugin)" "docs/customer/customer-env-assessment.md#2.2"
    fi
    info "Docker Compose: $(docker compose version --short)"

    # Python
    if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
        abort "未安装 Python 3.11+" "docs/deploy/customer-private.md#5"
    fi
    local py_cmd
    py_cmd=$(command -v python3 || command -v python)
    local py_ver
    py_ver=$("$py_cmd" -V 2>&1)
    info "Python: $py_ver"
    if ! "$py_cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
        abort "Python 版本必须 ≥ 3.11" "docs/deploy/customer-private.md#5"
    fi

    # 内存
    local total_mem_mb
    if [ "$(uname -s)" = "Darwin" ]; then
        total_mem_mb=$(( $(sysctl -n hw.memsize) / 1024 / 1024 ))
    else
        total_mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    fi
    info "总内存: ${total_mem_mb} MB"
    [ "$total_mem_mb" -lt 8000 ] && warn "内存 < 8 GB（推荐 16 GB），LangFuse 全栈可能 OOM"

    # 磁盘空间
    local free_gb
    free_gb=$(df -BG "$PROJECT_DIR" 2>/dev/null | awk 'NR==2 {gsub("G",""); print $4}' || df -h "$PROJECT_DIR" | awk 'NR==2 {gsub("G",""); print $4}')
    info "可用磁盘: ${free_gb} GB"
    [ "${free_gb%.*}" -lt 30 ] 2>/dev/null && warn "磁盘 < 30 GB，trace 增长可能撑爆"

    ok "前置检查通过"
}

# ============================================================
# Step 2 · .env 校验
# ============================================================
step2_env_check() {
    section "Step 2/10 · .env 校验"

    if [ ! -f "$ENV_FILE" ]; then
        abort ".env 不存在。请先 cp .env.customer.template .env 后填值" "docs/deploy/customer-private.md#4"
    fi

    # 检查 chmod 600（Linux/Mac only）
    if [ "$(uname -s)" != "Windows_NT" ] && [ -t 1 ]; then
        local perm
        perm=$(stat -f "%Lp" "$ENV_FILE" 2>/dev/null || stat -c "%a" "$ENV_FILE" 2>/dev/null)
        [ "$perm" != "600" ] && warn ".env 权限 $perm（推荐 600）：chmod 600 $ENV_FILE"
    fi

    # 必填字段
    local required=(
        CHECKPOINT_MYSQL_URI
        BUSINESS_MYSQL_URI
        QWEN_API_BASE
        QWEN_API_KEY
        QWEN_MODEL_STANDARD
        OTC_API_BASE_URL
        OTC_API_SECRET
    )
    local missing=()
    for key in "${required[@]}"; do
        local val
        val=$(env_get "$key")
        # 检查空 或 含未替换的 <FILL_*> 占位符
        if [ -z "$val" ] || [[ "$val" == *"<FILL"* ]]; then
            missing+=("$key")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        fail ".env 必填字段未填："
        printf '   - %s\n' "${missing[@]}"
        abort "请编辑 $ENV_FILE 替换 <FILL_*> 占位符" "docs/deploy/customer-private.md#4.2"
    fi

    ok ".env 必填字段全部就绪"

    # F4 灰度切流 advisory（非必填，仅提示状态）· §10 + §12
    local canary_val eval_user_val
    canary_val=$(env_get "CANARY_ROOM_IDS")
    eval_user_val=$(env_get "EVAL_USER_ID")
    if [ -z "$canary_val" ]; then
        info "F4 金丝雀未启用（CANARY_ROOM_IDS 空 → 任何 roomId 都视为非 canary）"
    elif [ "$canary_val" = "ALL" ]; then
        info "F4 金丝雀=ALL（全量已切流，所有 roomId 都视为 canary）"
    else
        local n_rooms
        n_rooms=$(echo "$canary_val" | awk -F, '{print NF}')
        info "F4 金丝雀启用，白名单群数 = $n_rooms"
    fi
    if [ -z "$eval_user_val" ] || [[ "$eval_user_val" == *"<FILL"* ]]; then
        info "EVAL_USER_ID 未配置（如不跑 scripts/probe_*_e2e.py 或 harness 真后端模式可忽略）"
    fi

    # F4.1 dry-run 模式 advisory（PR #112）
    local dry_run_val
    dry_run_val=$(env_get "DRY_RUN_BACKEND")
    if [ "$dry_run_val" = "true" ] || [ "$dry_run_val" = "1" ]; then
        warn "DRY_RUN_BACKEND=true（F4.1 shadow 期生效，写类调用被拦截）"
        warn "  → F4.2 切流前**务必**改回 false，否则用户下单会被拦截！"
        warn "  → 详见 docs/on-call-runbook.md §5.7"
    elif [ -n "$dry_run_val" ] && [ "$dry_run_val" != "false" ] && [ "$dry_run_val" != "0" ]; then
        warn "DRY_RUN_BACKEND 值未识别 ($dry_run_val)，按 false 处理"
    else
        info "DRY_RUN_BACKEND=false（生产路径，真后端真下单）"
    fi
}

# ============================================================
# Step 3 · MySQL 连通 + 版本（ADR 0009）
# ============================================================
step3_mysql_check() {
    section "Step 3/10 · MySQL 连通 + 版本"

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过实际连接"; return; }

    if ! command -v mysql >/dev/null 2>&1; then
        warn "未安装 mysql client，跳过版本验证（应用启动时仍会自检）"
        return
    fi

    local cp_uri
    cp_uri=$(env_get "CHECKPOINT_MYSQL_URI")

    # 用 Python urllib 正确解析（sed 处理含 @ 的密码会贪婪匹配出错；
    # 同时支持 URL-encoded 特殊字符如 %40 = @）
    local parsed
    parsed=$(python3 -c "
from urllib.parse import urlparse, unquote
u = urlparse('$cp_uri')
print(u.hostname or '')
print(u.port or 3306)
print(unquote(u.username or ''))
print(unquote(u.password or ''))
print((u.path or '').lstrip('/').split('?', 1)[0])
" 2>/dev/null) || abort "URI 解析失败（CHECKPOINT_MYSQL_URI 格式错？）" "docs/deploy/customer-private.md#4"

    local host port user pass db
    host=$(echo "$parsed" | sed -n '1p')
    port=$(echo "$parsed" | sed -n '2p')
    user=$(echo "$parsed" | sed -n '3p')
    pass=$(echo "$parsed" | sed -n '4p')
    db=$(echo "$parsed" | sed -n '5p')

    info "测试连接: $host:$port db=$db user=$user"

    # 用 --defaults-extra-file 避免 MYSQL_PWD 经 ps 泄漏到 /proc/<pid>/environ
    local creds_file
    creds_file=$(mktemp)
    chmod 600 "$creds_file"
    cat > "$creds_file" <<EOF
[client]
password=$pass
EOF
    trap 'rm -f "$creds_file"' RETURN

    if ! mysql --defaults-extra-file="$creds_file" -h "$host" -P "$port" -u "$user" -e "SELECT 1" >/dev/null 2>&1; then
        rm -f "$creds_file"
        abort "MySQL 连不通，检查 .env 中 CHECKPOINT_MYSQL_URI" "docs/troubleshooting-sop.md#4"
    fi

    local ver
    ver=$(mysql --defaults-extra-file="$creds_file" -h "$host" -P "$port" -u "$user" -N -e "SELECT VERSION()")
    rm -f "$creds_file"
    info "MySQL 版本: $ver"
    # ADR 0009: 8.0.19 ≤ v < 9.6.0
    if ! echo "$ver" | grep -qE '^(8\.0\.(19|[2-9][0-9])|9\.[0-5]\.)'; then
        warn "MySQL 版本 $ver 可能不在 ADR 0009 兼容范围（8.0.19 ≤ v < 9.6.0），AIOMySQLSaver 可能不可用"
    fi

    ok "MySQL 连通且版本兼容"
}

# ============================================================
# Step 4 · Java 后端连通
# ============================================================
step4_backend_check() {
    section "Step 4/10 · Java 后端连通"

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过实际连接"; return; }

    local url secret
    url=$(env_get "OTC_API_BASE_URL")
    secret=$(env_get "OTC_API_SECRET")

    # 用一个 read endpoint 测连通（securities-instrument/select）
    local endpoint="${url}/admin-api/integration/securities-instrument/select"
    info "测试 endpoint: $endpoint"

    local resp
    resp=$(curl -sf -m 10 -X POST "$endpoint" \
        -H "Content-Type: application/json" \
        -H "Token: $secret" \
        -d '{"keywordItems":[{"keyword":"600519","isFull":false}]}' 2>&1) \
        || abort "Java 后端连不通或返回非 2xx。response: $resp" "docs/troubleshooting-sop.md#3"

    # CommonResult.code = 0 才算业务成功
    if echo "$resp" | grep -q '"code":0'; then
        ok "Java 后端 200 + code=0"
    else
        warn "Java 后端 200 但 code != 0；可能 token 失效或参数问题: $resp"
    fi
}

# ============================================================
# Step 5 · LangFuse 启动
# ============================================================
step5_langfuse_up() {
    section "Step 5/10 · LangFuse 启动"

    if [ ! -f "${LANGFUSE_DIR}/docker-compose.yml" ]; then
        abort "找不到 ${LANGFUSE_DIR}/docker-compose.yml" "docs/deploy/langfuse-self-hosted.md"
    fi

    if [ ! -f "${LANGFUSE_DIR}/.env" ]; then
        abort "${LANGFUSE_DIR}/.env 不存在。参考 docs/deploy/langfuse-self-hosted.md §2.1 生成" "docs/deploy/langfuse-self-hosted.md#2"
    fi

    # 检查 3 个必填密钥
    for key in SALT ENCRYPTION_KEY NEXTAUTH_SECRET; do
        if ! grep -q "^${key}=" "${LANGFUSE_DIR}/.env"; then
            abort "${LANGFUSE_DIR}/.env 缺少 $key（用 openssl 生成）" "docs/deploy/langfuse-self-hosted.md#2.1"
        fi
    done

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过 docker compose"; return; }

    info "启动容器（约 30-60 秒首次 migration）"
    docker compose -f "${LANGFUSE_DIR}/docker-compose.yml" --env-file "${LANGFUSE_DIR}/.env" up -d \
        || abort "docker compose up 失败" "docs/deploy/langfuse-self-hosted.md#8"

    # 等所有容器 healthy（最多 120 秒）
    # 注意：旧 docker compose 输出 JSON array、新版输出 JSONL；用 docker ps
    # 的 health 状态过滤更稳定，避开 compose 输出格式差异
    info "等待容器健康检查..."
    local waited=0
    while [ "$waited" -lt 120 ]; do
        # 直接列容器，按 "name like langfuse-*" 过滤 + 查 health 状态
        # 用 inspect 拿每个容器的 .State.Health.Status（无 health 配置则返回 'none'）
        local compose_project
        compose_project=$(basename "$(dirname "${LANGFUSE_DIR}")")
        local containers
        containers=$(docker ps --filter "label=com.docker.compose.project=${compose_project}" --format '{{.Names}}')

        local all_ok=1
        local has_starting=0
        for c in $containers; do
            local hs
            hs=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c" 2>/dev/null)
            case "$hs" in
                healthy|none) ;;  # OK（无 healthcheck 的容器算 OK）
                starting)    has_starting=1; all_ok=0 ;;
                unhealthy|*) all_ok=0 ;;
            esac
        done

        if [ "$all_ok" = "1" ]; then
            ok "LangFuse 容器全部 healthy"
            return
        fi
        sleep 5
        waited=$((waited + 5))
        echo -n "."
    done
    echo
    abort "LangFuse 等待超时（120s）。看 docker compose logs" "docs/deploy/langfuse-self-hosted.md#8"
}

# ============================================================
# Step 6 · LangFuse 项目 + Key 提示
# ============================================================
step6_langfuse_key_prompt() {
    section "Step 6/10 · LangFuse 项目 + Key 配置"

    local pk sk
    pk=$(env_get "LANGFUSE_PUBLIC_KEY")
    sk=$(env_get "LANGFUSE_SECRET_KEY")

    if [ -n "$pk" ] && [ -n "$sk" ] && [[ "$pk" != *"<FILL"* ]] && [[ "$sk" != *"<FILL"* ]]; then
        ok "LangFuse key 已配置（pk=${pk:0:8}...）"
        return
    fi

    warn "LangFuse key 未配置。请按以下步骤："
    echo "   1. 浏览器访问 http://<host>:3000"
    echo "   2. 注册第一个用户（admin）"
    echo "   3. 创建组织 + 项目"
    echo "   4. 项目 → Settings → API Keys → Create"
    echo "   5. 复制 pk-lf-... 和 sk-lf-... 填到 .env："
    echo "      LANGFUSE_PUBLIC_KEY=pk-lf-..."
    echo "      LANGFUSE_SECRET_KEY=sk-lf-..."
    echo "   6. 重新跑：bash scripts/deploy-customer.sh --step 6"
    exit 1
}

# ============================================================
# Step 7 · Python 依赖
# ============================================================
step7_python_deps() {
    section "Step 7/10 · Python 依赖"

    cd "$PROJECT_DIR" || exit 1

    # 优先 uv，回退 pip
    if command -v uv >/dev/null 2>&1; then
        info "用 uv 安装依赖"
        [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过"; return; }
        uv sync --extra dev || abort "uv sync 失败" "docs/deploy/customer-private.md#5"
    else
        info "用 pip 安装依赖（venv）"
        [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过"; return; }
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        # shellcheck disable=SC1091
        . venv/bin/activate

        # 离线 wheel 优先（C1.14 #59 产出）
        if [ -d "wheelhouse" ]; then
            info "检测到 wheelhouse/，离线安装"
            pip install --no-index --find-links=wheelhouse -e ".[dev]" \
                || abort "离线 pip install 失败" "docs/deploy/customer-private.md#5.2"
        else
            pip install --upgrade pip
            pip install -e ".[dev]" || abort "pip install 失败" "docs/deploy/customer-private.md#5.1"
        fi
    fi

    # 验证 import
    "$PROJECT_DIR"/venv/bin/python -c "from app.config import get_settings; get_settings()" 2>/dev/null \
        || uv run python -c "from app.config import get_settings; get_settings()" \
        || abort "应用配置加载失败（检查 .env 字段）" "docs/troubleshooting-sop.md"

    ok "Python 依赖安装 + 配置加载成功"
}

# ============================================================
# Step 8 · 应用启动
# ============================================================
step8_app_start() {
    section "Step 8/10 · 应用启动"

    cd "$PROJECT_DIR" || exit 1

    # 已经在运行？
    if curl -sf -m 3 http://localhost:8000/health >/dev/null 2>&1; then
        ok "应用已在运行（:8000）"
        return
    fi

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过启动"; return; }

    info "后台启动 uvicorn :8000（生产推荐用 systemd 见 docs/deploy/customer-private.md#6.2）"
    local cmd
    if command -v uv >/dev/null 2>&1; then
        cmd="nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
    else
        cmd="nohup venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"
    fi
    $cmd >> "${PROJECT_DIR}/app.log" 2>&1 &
    local pid=$!
    echo "$pid" > "${PROJECT_DIR}/app.pid"
    info "PID: $pid → ${PROJECT_DIR}/app.pid（日志：app.log）"

    # 短等待让 uvicorn 完成绑定；Step 9 健康检查会再轮询 30 秒
    sleep 5
    ok "应用已后台启动（PID $pid，Step 9 健康检查继续验证）"
}

# ============================================================
# Step 9 · 健康检查
# ============================================================
step9_health_check() {
    section "Step 9/10 · 健康检查"

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过"; return; }

    local waited=0
    while [ "$waited" -lt 30 ]; do
        if curl -sf -m 3 http://localhost:8000/health >/dev/null 2>&1; then
            ok "GET /health 200"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
    [ "$waited" -ge 30 ] && abort "/health 30 秒未通" "docs/troubleshooting-sop.md#1"

    # /metrics（C1.5 #65）
    if curl -sf -m 3 http://localhost:8000/metrics >/dev/null 2>&1; then
        ok "GET /metrics 200（监控埋点工作）"
    else
        warn "/metrics 不可用（C1.5 可能未生效）"
    fi

    # /ready（D2.6 #72）· 4 个上游探测：mysql / langfuse / llm / java_backend
    # 200 = 全绿；503 = 至少一个 fail（degraded）
    local ready_status ready_tmp
    ready_tmp=$(mktemp)
    ready_status=$(curl -s -m 10 -o "$ready_tmp" -w '%{http_code}' \
        http://localhost:8000/ready 2>/dev/null)
    case "$ready_status" in
        200)
            ok "GET /ready 200（4 个上游全绿）"
            ;;
        503)
            warn "GET /ready 503（degraded，详见 checks）："
            cat "$ready_tmp" 2>/dev/null | head -3
            warn "  → 上线前请先排查失败的上游（python scripts/metrics_snapshot.py 查健康检查段）"
            ;;
        *)
            warn "GET /ready HTTP $ready_status（D2.6 路由可能未注册）"
            ;;
    esac
    rm -f "$ready_tmp"
}

# ============================================================
# Step 10 · Smoke 自检
# ============================================================
step10_smoke() {
    section "Step 10/10 · Smoke 自检"

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过"; return; }

    # 用 -s（silent）但不用 -f（让 4xx/5xx 也返回 body）；
    # 单独拿 HTTP 状态码 + body，区分"应用 5xx"vs"业务回复偏差"
    _run_smoke() {
        local payload="$1"
        local body status tmp
        tmp=$(mktemp)
        status=$(curl -s -m 30 -o "$tmp" -w '%{http_code}' \
            -X POST http://localhost:8000/v1/workflows/run \
            -H "Content-Type: application/json" -d "$payload" 2>/dev/null)
        body=$(cat "$tmp" 2>/dev/null)
        rm -f "$tmp"
        echo "${status}|${body}"
    }

    # 注：inputs 字段名按 app/api/routes.py _INPUT_FIELD_MAP 约定
    # （rawContent/raw_content → raw_text；roomId → room_id 等）
    info "Case 1: 完整代码询价"
    local r1 status1 body1
    r1=$(_run_smoke '{"inputs":{"raw_content":"600519.SH 询价 3 个月平值看涨","conversationId":"smoke-001","roomId":"smoke-room","userId":"smoke-user","messageId":1},"response_mode":"blocking","user":"smoke-test"}')
    status1=${r1%%|*}; body1=${r1#*|}
    if [ "$status1" != "200" ]; then
        warn "Case 1 HTTP $status1（应用层错而非业务回复偏差）：$body1"
    elif echo "$body1" | grep -q "600519"; then
        ok "Case 1 包含 600519"
    else
        warn "Case 1 响应未含 600519: $body1"
    fi

    info "Case 2: 中文简称"
    local r2 status2 body2
    r2=$(_run_smoke '{"inputs":{"raw_content":"贵州茅台 询价","conversationId":"smoke-002","roomId":"smoke-room","userId":"smoke-user","messageId":2},"response_mode":"blocking","user":"smoke-test"}')
    status2=${r2%%|*}; body2=${r2#*|}
    if [ "$status2" != "200" ]; then
        warn "Case 2 HTTP $status2（应用层错）：$body2"
    elif echo "$body2" | grep -qE "600519|茅台"; then
        ok "Case 2 包含 600519 或茅台"
    else
        warn "Case 2 响应可能异常: $body2"
    fi

    info "Case 3: 未知标的（fallback）"
    local r3 status3 body3
    r3=$(_run_smoke '{"inputs":{"raw_content":"完全不存在的标的xyz 询价","conversationId":"smoke-003","roomId":"smoke-room","userId":"smoke-user","messageId":3},"response_mode":"blocking","user":"smoke-test"}')
    status3=${r3%%|*}; body3=${r3#*|}
    if [ "$status3" != "200" ]; then
        warn "Case 3 HTTP $status3（应用层错）：$body3"
    elif echo "$body3" | grep -qE "无法识别|抱歉|没完全理解"; then
        ok "Case 3 fallback 触发"
    else
        warn "Case 3 fallback 未触发: $body3"
    fi
}

# ============================================================
# Step 11 · 真后端 E2E probe（可选 · 仅 EVAL_USER_ID 配置时跑）
# ============================================================
step11_real_backend_probe() {
    section "Step 11/11 · 真后端 E2E probe（PR #111）"

    [ "$DRY_RUN" = "1" ] && { warn "dry-run 跳过"; return; }

    # 前置：EVAL_USER_ID + EVAL_ROOM_ID 必填，否则跳过（不阻塞 deploy）
    local eval_user eval_room
    eval_user=$(env_get "EVAL_USER_ID")
    eval_room=$(env_get "EVAL_ROOM_ID")
    if [ -z "$eval_user" ] || [[ "$eval_user" == *"<FILL"* ]] \
        || [ -z "$eval_room" ] || [[ "$eval_room" == *"<FILL"* ]]; then
        warn "EVAL_USER_ID / EVAL_ROOM_ID 未配置 → 跳过真后端 probe"
        warn "  → 客户授权后填 .env §12，再 bash scripts/deploy-customer.sh --only 11 单跑"
        return
    fi

    info "EVAL 账号已配置，跑真后端 E2E probe（4 target × 13 cases）..."
    info "（任一 exception/unreachable → warn，不阻塞 deploy）"

    if python3 "${PROJECT_DIR}/scripts/probe_real_backend_e2e.py" \
            --target all --stop-on-fail 2>&1 | tee -a "$LOG_FILE"; then
        ok "真后端 probe 全通"
    else
        warn "真后端 probe 失败（详见 .harness-runs/probe-*/report.md）"
        warn "  → 处置：检查 OTC_API_BASE_URL / GOATS 凭证 / 客户后端状态"
    fi
}

# ============================================================
# Main
# ============================================================
main() {
    section "${BOLD}otc-agent 客户现场部署${RESET}"
    info "项目目录: $PROJECT_DIR"
    info "日志文件: $LOG_FILE"
    [ "$DRY_RUN" = "1" ] && warn "DRY-RUN 模式：只验证前置条件，不实际改动"

    should_run_step 1  && step1_preflight
    should_run_step 2  && step2_env_check
    should_run_step 3  && step3_mysql_check
    should_run_step 4  && step4_backend_check
    should_run_step 5  && step5_langfuse_up
    should_run_step 6  && step6_langfuse_key_prompt
    should_run_step 7  && step7_python_deps
    should_run_step 8  && step8_app_start
    should_run_step 9  && step9_health_check
    should_run_step 10 && step10_smoke
    should_run_step 11 && step11_real_backend_probe

    section "${GREEN}部署完成${RESET}"
    echo
    echo "📊 LangFuse 控制台: http://localhost:3000"
    echo "🚀 应用 API:        http://localhost:8000"
    echo "💓 健康检查:        http://localhost:8000/health"
    echo "📈 监控指标:        http://localhost:8000/metrics"
    echo
    echo "📖 接入企微 Webhook 见 docs/deploy/customer-private.md §8"
    echo "📖 故障处理 见 docs/on-call-runbook.md"
    echo
}

main "$@"
