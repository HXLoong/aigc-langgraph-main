# Windows 本地开发环境搭建

> 2026-05-06 · 全程可复制粘贴 · 不再需要 Java 后端

## 前置条件

| 软件 | 版本要求 | 验证命令 |
|------|---------|----------|
| Windows | 10/11 Pro | — |
| Docker Desktop | 最新版，已启动 | `docker ps` |
| Python | 3.11+ | `python --version` |
| uv | 最新版 | `uv --version` |
| Git Bash | 任意版本 | `bash --version` |

以下命令全部在 **Git Bash** 中运行（不是 PowerShell，不是 CMD）。

---

## 1. 克隆仓库

```bash
git clone git@github.com:GZTL-AI/aigc-langgraph.git
cd aigc-langgraph
```

如果已经 clone 过，切到最新：

```bash
cd e:/VSCode/aigc-langgraph
git checkout feature-hyk
git pull origin feature-hyk
```

---

## 2. 安装 Python 依赖

```bash
uv sync
```

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，改成你的值：

```ini
QWEN_API_KEY=sk-your-actual-qwen-api-key
```

其他行不用改，默认值就是本地 localhost 地址。

---

## 4. 启动 Docker 基础设施

### 4.1 MySQL

```bash
docker compose up -d mysql
```

### 4.2 Redis 集群

```bash
docker rm -f otc-agent-redis 2>/dev/null

docker run -d \
  --name otc-agent-redis \
  -p 6379:6379 \
  -v otc-redis-data:/data \
  redis:7-alpine \
  redis-server \
    --requirepass shareredis7 \
    --cluster-enabled yes \
    --cluster-config-file nodes.conf \
    --cluster-announce-ip 127.0.0.1 \
    --cluster-announce-port 6379
```

**首次启动需要分配 slot**（只需要做一次，以后重启跳过）：

```bash
# Git Bash 不支持 seq，用这条：
docker exec otc-agent-redis redis-cli -a shareredis7 CLUSTER ADDSLOTS $(echo {0..16383})
```

如果上面报错，用兼容写法：

```bash
for i in $(seq 0 1000 16000); do
  end=$((i + 999))
  [ $end -gt 16383 ] && end=16383
  docker exec otc-agent-redis redis-cli -a shareredis7 CLUSTER ADDSLOTS $(seq $i $end) 2>/dev/null
done
```

### 4.3 RabbitMQ

```bash
docker rm -f otc-agent-rabbitmq 2>/dev/null

docker run -d \
  --name otc-agent-rabbitmq \
  -p 5672:5672 \
  -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=default_user_TGrdJ5tdzHzeNmVA1Nr \
  -e RABBITMQ_DEFAULT_PASS=7XQCrSyY7VzKYKvpZL2DKFkHDK3s1hze \
  -e RABBITMQ_DEFAULT_VHOST=ai-trading-assistant \
  rabbitmq:3.13-management-alpine

# 等 RabbitMQ 启动完成（约 5 秒），再设权限
sleep 5
docker exec otc-agent-rabbitmq rabbitmqctl set_permissions \
  -p ai-trading-assistant \
  default_user_TGrdJ5tdzHzeNmVA1Nr \
  ".*" ".*" ".*"
```

### 4.4 验证 Docker

```bash
docker ps --filter "name=otc-agent" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

预期看到 3 个容器：`otc-agent-mysql`、`otc-agent-redis`、`otc-agent-rabbitmq`。

---

## 5. 导入数据库（可选）

仅当需要 MySQL checkpoint 持久化时才需要。SQL 文件从后端仓库单独获取。

```bash
# 建库
docker compose exec -T mysql mysql -uroot -prootpassword -e \
  "CREATE DATABASE IF NOT EXISTS goats_ai_trading_dev1 DEFAULT CHARACTER SET utf8mb4"

# 导入（替换为你的 SQL 文件路径）
docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < /path/to/goats_ai_trading_dev1.sql

docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < /path/to/goats_ai_trading_dev1-data.sql
```

---

## 6. 启动应用服务（2 个终端）

### 终端 A：Mock API（端口 8099）

```bash
cd e:/VSCode/aigc-langgraph
uv run uvicorn mock_api.server:app --host 0.0.0.0 --port 8099
```

### 终端 B：LangGraph（端口 8000）

```bash
cd e:/VSCode/aigc-langgraph
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 验证

```bash
curl http://localhost:8099/
# → {"service":"GOATS Mock API","endpoints":31,...}

curl http://localhost:8000/health
# → {"status":"ok","environment":"development","use_langgraph":true}
```

---

## 7. 运行测试

### 单元测试（不需要起任何服务）

```bash
cd e:/VSCode/aigc-langgraph

# 全部
uv run pytest tests/ -v

# ticker 子图专项（27 条，约 1 秒）
uv run pytest -s tests/test_ticker.py -v
```

### 集成测试（需要 mock_api 和 LangGraph 都跑着）

```bash
uv run python tests/run_integration_test.py
```

预期 `14 PASS, 0 FAIL`。

---

## 8. 手动发消息测试

```bash
curl -X POST http://localhost:8000/v1/message \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-001",
    "message_id": "msg-001",
    "room_id": "room-001",
    "user_id": "user-001",
    "guid": "guid-001",
    "raw_content": "互换下单 帮我买入1000股腾讯控股"
  }'
```

---

## 9. 架构速览

```
┌─────────────────────────────────────────────────┐
│                 您的本地机器                       │
│                                                   │
│   Git Bash 终端 A:  mock_api (8099)               │
│   Git Bash 终端 B:  LangGraph (8000)              │
│                                                   │
│   Docker Desktop:                                 │
│     otc-agent-mysql      3306                     │
│     otc-agent-redis      6379 (cluster mode)      │
│     otc-agent-rabbitmq   5672, 15672              │
│                                                   │
│   外部网络:                                        │
│     dashscope.aliyuncs.com  ← LLM 调用            │
└─────────────────────────────────────────────────┘
```

mock_api（8099）一个端口覆盖了：
- 20 个 GOATS 内部接口（期权/互换/交易对手/投管/Dify）
- 6 个后端业务接口（swap-order / financial-orders / counterparty / conversation-orders / bot-name / set-intent）

不再需要 Java 后端。

---

## 10. 踩坑记录

| 问题 | 原因 | 解决 |
|------|------|------|
| Redis `seq` 参数过长 | Git Bash 下 `$(seq 0 16383)` 展开后超限 | 用 `{0..16383}` 或分批 1000 |
| Redis `Slot is already busy` | 上次已分配，数据卷持久化 | 正常，跳过 |
| Mock 启动报 `No module named 'mock_api'` | 还没执行 `uv sync` | 回到第 2 步 |
| 集成测试 api_code=400 | 之前连的 Java 后端或 mock_goats_api | 确保 mock_api 在 8099 端口启动 |
| VPN 断开时请求超时 15s | 标的查询接口是内网地址 | mock_api 替代了其他接口，标的查询仍需 VPN |

---

## 11. 目录结构

```
aigc-langgraph/
├── app/                      # LangGraph 主代码
│   ├── main.py               # FastAPI 入口
│   ├── state.py              # AgentState 定义
│   ├── graphs/               # 主图
│   ├── subgraphs/            # swap / option / close / ticker
│   ├── nodes/                # ingest / route / persist / render
│   ├── prompts/              # 23 个 Dify 提示词
│   ├── tools/                # 后端 HTTP 客户端
│   └── llm/                  # Qwen LLM 客户端
├── mock_api/                 # Mock 服务（26 个接口）
│   ├── server.py
│   └── README.md
├── tests/
│   ├── run_integration_test.py   # 14 条全链路集成测试
│   ├── test_ticker.py            # ticker 子图 27 条测试
│   ├── test_e2e.py
│   └── test_models.py
├── docs/
│   ├── training/WINDOWS_LOCAL_SETUP.md  # 本文档
│   └── TEST_AND_CONNECTIVITY_STATUS.md
├── docker-compose.yml
├── .env.example
└── HOW_TO_RUN.md
```
