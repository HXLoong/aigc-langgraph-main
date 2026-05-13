#!/bin/bash
# 本地开发启动脚本：自动建 SSH 隧道 → 启动服务 → Ctrl+C 时清理隧道
set -e

SSH_HOST="root@47.121.188.230"
PORTS="-L 3306:localhost:3306 -L 6379:localhost:6379 -L 5672:localhost:5672 -L 15672:localhost:15672"

cleanup() {
    echo "关闭 SSH 隧道..."
    pkill -f "ssh.*-L.*47.121.188.230" 2>/dev/null || true
}
trap cleanup EXIT

echo "建立 SSH 隧道到 $SSH_HOST ..."
ssh -f -N -o ExitOnForwardFailure=yes $PORTS $SSH_HOST
echo "SSH 隧道已建立"

echo "启动 uvicorn (端口 8000)..."
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
