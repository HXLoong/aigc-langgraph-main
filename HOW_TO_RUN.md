# HOW TO RUN — 场外衍生品 AI 指令助手

本目录 `aigc-langgraph`（LangGraph 智能代理）+ 兄弟目录 `aigc`（Java Spring Boot 后端）。

## 一、架构概览

```
企微消息 → LangGraph (8000) → LLM 意图解析 / 参数提取
                  ↓
            Java Backend (48080) → 执行业务操作
                  ↓
        MySQL (3306) + Redis (6379) + RabbitMQ (5672)
```

## 二、依赖

| 依赖 | 用途 |
|------|------|
| Docker Desktop | MySQL / Redis / RabbitMQ 容器 |
| Python 3.11+ | LangGraph FastAPI |
| Java 17 | Spring Boot 后端 |
| 公网 | LLM 调用 dashscope.aliyuncs.com |

VPN 可选（见下方两种模式）。

## 三、启动流程

### 模式 A：无 VPN（本地 Docker 全栈）

#### 1. 启动 Docker 基础设施

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

# 首次启动：分配集群 slots
docker exec otc-agent-redis redis-cli -a shareredis7 CLUSTER ADDSLOTS $(seq 0 16383)

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

#### 2. 导入数据库

将两个 SQL 文件（`goats_ai_trading_dev1.sql` + `goats_ai_trading_dev1-data.sql`）放到项目根目录或任意路径，然后执行：

```bash
docker compose exec -T mysql mysql -uroot -prootpassword -e \
  "CREATE DATABASE IF NOT EXISTS goats_ai_trading_dev1 DEFAULT CHARACTER SET utf8mb4"

# 替换路径为 SQL 文件实际位置
docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < goats_ai_trading_dev1.sql

docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 \
  < goats_ai_trading_dev1-data.sql
```

SQL 文件从后端代码仓库或单独获取。

#### 3. 启动 Mock GOATS

```bash
uv run uvicorn mock_goats_api.server:app --host 0.0.0.0 --port 8099 &
```

#### 4. 启动 LangGraph

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

#### 5. 启动 Java 后端

```bash
cd ../aigc/api

MYSQL_URL="jdbc:mysql://localhost:3306/goats_ai_trading_dev1?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&nullCatalogMeansCurrent=true&rewriteBatchedStatements=true" \
MYSQL_USERNAME="root" \
MYSQL_PASSWORD="rootpassword" \
REDIS_CLUSTER_NODES="localhost:6379" \
REDIS_PASSWORD="shareredis7" \
RABBITMQ_ADDRESSES="localhost:5672" \
RABBITMQ_USERNAME="default_user_TGrdJ5tdzHzeNmVA1Nr" \
RABBITMQ_PASSWORD="7XQCrSyY7VzKYKvpZL2DKFkHDK3s1hze" \
RABBITMQ_VIRTUAL_HOST="ai-trading-assistant" \
GOATS_API_BASE_URL="http://localhost:8099" \
PLATFORM_API_ENABLED="false" \
DIFY_ACCOUNT_ENABLED="false" \
DIFY_OATOAUTH2_ENABLED="false" \
java -jar yudao-server/target/yudao-server.jar --spring.profiles.active=local
```

启动约需 90 秒。验证：

```bash
curl http://localhost:48080/
# → {"code":401,"msg":"账号未登录"}  说明后端正常
```

### 模式 B：有 VPN（远程内网服务）

如果 VPN 能连到广发内网（`10.x.x.x`），则只需：

```bash
# 步骤 1-4 同上（Docker MySQL + Mock GOATS + LangGraph）

# 步骤 5：直接启动后端，无需环境变量覆盖
cd ../aigc/api
java -jar yudao-server/target/yudao-server.jar --spring.profiles.active=local
```

后端会自动连内网的 MySQL (`10.129.69.30:15321`)、Redis 集群 (`10.51.135.x`)、RabbitMQ (`10.51.135.x`)。

## 四、验证

### 健康检查

```bash
curl http://localhost:8000/health        # LangGraph
curl http://localhost:48080/             # Java Backend
curl http://localhost:8099/              # Mock GOATS
docker ps --filter "name=otc-agent"      # Docker 容器
```

### 单元测试

```bash
pytest tests/ -v
```

### 集成测试（14 条，验证全链路）

```bash
python tests/run_integration_test.py
```

预期输出：**14 PASS**，每条的 trace 显示完整节点链路：

```
[01/14] Swap-文本下单        → dispatch → ticker → classify → extract_place_order → call_swap_api
[06/14] Option-快速询价      → detect_quick_query → fast_query_api
[09/14] Close-持仓查询       → classify_close → extract_holding_query → call_close_api
[13/14] Unknown-兜底         → render_reply
...
结果: 14 PASS, 0 FAIL
```

### 手动发消息

```bash
curl -X POST http://localhost:8000/v1/message \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"t1","message_id":"m1","room_id":"r1","user_id":"u1","guid":"g1","raw_content":"互换下单 帮我买入1000股腾讯控股"}'
```

响应包含 `product_type`、`intent`、`trace`（节点链路）、`api_code`。

## 五、服务清单

| 服务 | 端口 | 启动方式 |
|------|------|----------|
| MySQL 8.0 | 3306 | `docker compose up -d mysql` |
| Redis 7 (cluster) | 6379 | `docker run`（见上方） |
| RabbitMQ 3.13 | 5672 | `docker run`（见上方） |
| Mock GOATS API | 8099 | `uv run uvicorn mock_goats_api.server:app --port 8099` |
| LangGraph FastAPI | 8000 | `uv run uvicorn app.main:app --port 8000 --reload` |
| Java Spring Boot | 48080 | `java -jar yudao-server.jar --spring.profiles.active=local` |

## 六、目录结构

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
├── tests/
│   ├── run_integration_test.py  # 集成测试脚本
│   ├── test_e2e.py              # 端到端测试
│   └── test_models.py           # 模型测试
├── mock_goats_api/          # Mock 标的查询服务
├── docs/                    # 架构 / 开发 / 测试文档
├── docker-compose.yml       # MySQL 容器
└── .env                     # LangGraph 环境变量

aigc/
├── api/yudao-server/        # Spring Boot 应用
│   └── src/main/resources/
│       └── application-local.yaml  # 后端配置（保留内网默认值）
├── goats_ai_trading_dev1.sql      # 数据库表结构
├── goats_ai_trading_dev1-data.sql # 数据库数据
└── api/.env.local          # 本地环境变量覆盖（无 VPN 时使用）
```
