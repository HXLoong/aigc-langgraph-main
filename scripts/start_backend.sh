#!/bin/bash
# 一键启动 LangGraph 后端（连真实 GOATS）
set -e

# 检查 .env
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ .env 文件不存在: $ENV_FILE"
    exit 1
fi

OTC_URL=$(grep "^OTC_API_BASE_URL=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
echo "OTC_API_BASE_URL = $OTC_URL"
echo ""

cleanup() {
    echo "关闭服务..."
    kill $APP_PID 2>/dev/null || true
}
trap cleanup EXIT INT

echo "=== LangGraph (端口 8000) ==="
cd "$PROJECT_DIR"
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
APP_PID=$!

echo ""
echo "LangGraph 已启动 → http://localhost:8000"
echo "OTC 后端 → $OTC_URL"
echo ""
wait
