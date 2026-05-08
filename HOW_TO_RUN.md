# HOW TO RUN — 场外衍生品 AI 指令助手

本目录 `aigc-langgraph`（LangGraph 智能代理），无需 Java 后端即可本地运行。

## 一、架构概览

```
企微消息 → LangGraph (8000) → LLM 意图解析 / 参数提取
                  ↓
            mock_api (8099) → 模拟全部后端接口（GOATS + 业务）
                  ↓
        MySQL (3306) + Redis (6379) + RabbitMQ (5672)
```

## 二、依赖

| 依赖 | 用途 |
|------|------|
| Docker Desktop | MySQL / Redis / RabbitMQ 容器 |
| Python 3.11+ | LangGraph FastAPI + mock_api |
| 公网 | LLM 调用 dashscope.aliyuncs.com |

不再需要 Java 17 / Spring Boot，mock_api 已覆盖全部后端接口。

## 三、启动流程

### 1. 环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 QWEN_API_KEY
```

关键默认值（本地开发无需改动）：

```ini
OTC_API_BASE_URL=http://localhost:8099    # mock_api 地址
GOATS_BASE_URL=http://localhost:8099      # 同端口，mock 同时提供
```

### 2. 启动 Docker 基础设施

```bash
# MySQL
docker compose up -d mysql

# Redis（集群模式，单节点）
docker rm -f otc-agent-redis
docker run -d --name otc-agent-redis -p 6379:6379 \
  -v otc-redis-data:/data \
  redis:7-alpine redis-server \
    --requirepass shareredis7 \
    --cluster-enabled yes \
    --cluster-config-file nodes.conf \
    --cluster-announce-ip 127.0.0.1 \
    --cluster-announce-port 6379

# 首次启动：分配集群 slots（后续重启跳过，数据卷持久化）
docker exec otc-agent-redis redis-cli -a shareredis7 CLUSTER ADDSLOTS $(seq 0 16383)
# Windows: seq 参数过长时分批执行，或使用 git bash

# RabbitMQ
docker rm -f otc-agent-rabbitmq
docker run -d --name otc-agent-rabbitmq -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=default_user_TGrdJ5tdzHzeNmVA1Nr \
  -e RABBITMQ_DEFAULT_PASS=7XQCrSyY7VzKYKvpZL2DKFkHDK3s1hze \
  -e RABBITMQ_DEFAULT_VHOST=ai-trading-assistant \
  rabbitmq:3.13-management-alpine

docker exec otc-agent-rabbitmq rabbitmqctl set_permissions \
  -p ai-trading-assistant default_user_TGrdJ5tdzHzeNmVA1Nr ".*" ".*" ".*"
```

### 3. 导入数据库（可选，仅 checkpoint 持久化需要）

SQL 文件从后端仓库单独获取，放到项目根目录后执行：

```bash
docker compose exec -T mysql mysql -uroot -prootpassword -e \
  "CREATE DATABASE IF NOT EXISTS goats_ai_trading_dev1 DEFAULT CHARACTER SET utf8mb4"

docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < goats_ai_trading_dev1.sql

docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < goats_ai_trading_dev1-data.sql
```

### 4. 启动 mock_api（端口 8099）

一个服务同时模拟 **20 个 GOATS 内部接口 + 6 个后端业务接口**，替代旧的 mock_goats_api + Java 后端：

```bash
uv run uvicorn mock_api.server:app --host 0.0.0.0 --port 8099 &
```

验证：
```bash
curl http://localhost:8099/
# → {"service":"GOATS Mock API","endpoints":31,...}
```

### 5. 启动 LangGraph（端口 8000）

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

验证：
```bash
curl http://localhost:8000/health
# → {"status":"ok","environment":"development","use_langgraph":true}
```

## 四、验证

### 健康检查

```bash
curl http://localhost:8000/health        # LangGraph
curl http://localhost:8099/              # Mock API（GOATS + 后端）
docker ps --filter "name=otc-agent"      # Docker 容器
```

### 单元测试

```bash
pytest tests/ -v                              # 全部测试
pytest -s tests/test_ticker.py -v             # ticker 子图专项（27 条）
```

### 集成测试（14 条全链路）

```bash
python tests/run_integration_test.py
```

预期输出：**14 PASS**，api_code=0（mock 返回成功码）：

```
[01/14] Swap-文本下单   → dispatch → ticker → classify → extract_place_order → call_swap_api
[06/14] Option-快速询价 → detect_quick_query → fast_query_api
[09/14] Close-持仓查询  → classify_close → extract_holding_query → call_close_api
...
结果: 14 PASS, 0 FAIL
```

### 手动发消息

```bash
curl -X POST http://localhost:8000/v1/message \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"t1","message_id":"m1","room_id":"r1","user_id":"u1","guid":"g1","raw_content":"互换下单 帮我买入1000股腾讯控股"}'
```

## 五、服务清单

| 服务 | 端口 | 启动方式 |
|------|------|----------|
| MySQL 8.0 | 3306 | `docker compose up -d mysql` |
| Redis 7 (cluster) | 6379 | `docker run`（见上方） |
| RabbitMQ 3.13 | 5672 | `docker run`（见上方） |
| Mock API | 8099 | `uv run uvicorn mock_api.server:app --port 8099` |
| LangGraph FastAPI | 8000 | `uv run uvicorn app.main:app --port 8000 --reload` |

mock_api 已覆盖 Java 后端的 6 个业务接口，本地开发不需要启动 Java 后端。

## 六、mock_api 接口清单

mock_api 在 8099 端口同时提供两类接口：

### GOATS 内部接口（20 个）

期权 11 个 + 收益互换 6 个 + 交易对手 1 个 + 投管系统 1 个 + Dify 1 个

### 后端业务接口（6 个，对应 OtcBackendClient）

| 方法 | 路径 | OtcBackendClient 方法 |
|------|------|----------------------|
| POST | `/admin-api/swap-order/operate` | `swap_operate()` |
| POST | `/admin-api/financial-orders/operate` | `financial_orders_operate()` |
| GET | `/admin-api/counterparty/info/list` | `counterparty_list()` |
| POST | `/admin-api/swap-order/get-conversation-orders` | `conversation_orders()` |
| POST | `/admin-api/business/config/bot/name/list` | `bot_name_list()` |
| POST | `/admin-api/openapi/xbot/message/set-intent` | `set_intent()` |

响应格式：`{"code": 0, "data": ..., "msg": "success"}`

模拟错误：任意接口加 `?_error=1` 参数返回 400。

## 七、目录结构

```
aigc-langgraph/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── state.py             # AgentState 定义
│   ├── graphs/main_graph.py # 主图
│   ├── subgraphs/           # swap / option / close / ticker
│   ├── nodes/               # ingest / route / persist / render
│   ├── prompts/             # 23 个 Dify 提示词（只读）
│   ├── tools/otc_backend.py # 后端 HTTP 客户端
│   └── llm/clients.py       # Qwen LLM 客户端
├── mock_api/                # Mock 服务（GOATS 20 + 后端 6 个接口）
├── tests/
│   ├── run_integration_test.py  # 集成测试脚本
│   ├── test_ticker.py           # ticker 子图测试（27 条）
│   ├── test_e2e.py              # 端到端测试
│   └── test_models.py           # 模型测试
├── docs/                    # 架构 / 开发 / 测试文档
├── docker-compose.yml       # MySQL 容器
└── .env.example             # 环境变量模板
```
