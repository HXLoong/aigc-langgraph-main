# HOW TO RUN — 场外衍生品 AI 指令助手

本目录 `aigc-langgraph`（LangGraph 智能代理）。

> 当前阶段：M1 已完成 → M2 待启动。本文档反映 M1 完成后的状态。

## 一、架构概览

```text
企微消息 → Java Worker → POST /v1/workflows/run → LangGraph (8000) → LLM 意图解析 / 参数提取
                                                          ↓
                                                LangFuse (3000) — trace / dataset / eval / annotation
                                                          ↓
                                         MySQL (3306) — checkpoint + 业务库
```

## 二、依赖

| 依赖 | 用途 |
|------|------|
| Docker Desktop | MySQL + LangFuse stack 容器 |
| Python 3.11+ | LangGraph FastAPI + harness CLI |
| 公网 | LLM 调用 dashscope.aliyuncs.com |

不再需要 Java 后端 / Spring Boot，直接对接真实后端。

## 三、启动流程

### 1. 环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 QWEN_API_KEY
```

### 2. 启动 MySQL

```bash
docker compose up -d mysql
```

### 3. 启动 LangFuse self-hosted（ADR 0014）

```bash
# 准备 LangFuse env
cp infra/langfuse/.env.example infra/langfuse/.env

# 生成 3 个必填密钥
echo "SALT=$(openssl rand -base64 32)" >> infra/langfuse/.env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> infra/langfuse/.env
echo "NEXTAUTH_SECRET=$(openssl rand -base64 32)" >> infra/langfuse/.env

# 启动
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 浏览器访问 → 注册账号 → 创建组织 → 创建项目 → 取 API Key
open http://localhost:3000
```

把生成的 API Key 写到 `.env`：

```ini
ENABLE_LANGFUSE=true
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### 4. 启动 LangGraph（端口 8000）

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

验证：

```bash
curl http://localhost:8000/health
```

## 四、验证

### 健康检查

```bash
curl http://localhost:8000/health        # LangGraph
curl http://localhost:3000/              # LangFuse UI
docker ps --filter "name=otc-agent" --filter "name=langfuse"
```

### 单元测试

```bash
pytest tests/ -v                 # 全套（smoke + tools + api + harness）
pytest tests/test_smoke.py -v    # 仅 M1 smoke（图编译 + 端到端 stub run + @safe_node 异常捕获）
```

> `tests/api/` 是 GOATS 接口连通性测试，需真实后端 + VPN，已通过 pyproject `addopts = "--ignore=tests/api"` 默认跳过；M3 联调时手动 `pytest tests/api/`。

### Harness CLI

```bash
python -m harness run                     # 跑 golden 全集（M2 后扩到 200+）
python -m harness run --case g042         # 单 case
python -m harness diff <run-a> <run-b>    # 比对两次 run（如 dify vs langgraph 的 shadow）
python -m harness sync-golden             # tests/fixtures/*.jsonl ↔ LangFuse dataset
```

### 手动发消息（兼容 Dify Workflow Run API）

```bash
curl -X POST http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "conversation_id": "t1",
      "message_id": 1,
      "room_id": "r1",
      "user_id": "u1",
      "guid": "g1",
      "raw_content": "互换下单 帮我买入1000股腾讯控股"
    },
    "response_mode": "blocking",
    "user": "t1"
  }'
```

## 五、服务清单

| 服务 | 端口 | 启动方式 |
|------|------|----------|
| MySQL 8.0.36 | 3306 | `docker compose up -d mysql` |
| LangFuse Web | 3000 | `docker compose -f infra/langfuse/docker-compose.yml ... up -d` |
| LangFuse Worker | 3030 | 同上（一并启动） |
| LangGraph FastAPI | 8000 | `uvicorn app.main:app --port 8000 --reload` |

## 六、目录结构

```text
aigc-langgraph/
├── app/                          # LangGraph 应用层
│   ├── main.py                   # FastAPI 入口
│   ├── api/routes.py             # POST /v1/workflows/run
│   ├── graph/                    # state + safe_node + main 主图
│   ├── nodes/                    # ingest / persist / render
│   ├── tools/                    # 3 个 Protocol: OptionClient / SwapClient / TickerClient
│   ├── llm/clients.py            # Qwen LLM 客户端
│   ├── checkpointer/factory.py   # AIOMySQLSaver
│   └── prompts/                  # 23 个 Dify 提示词资产
├── harness/                      # 评测台 CLI
├── infra/langfuse/               # LangFuse self-hosted compose
├── docs/adr/                     # 15 个架构决定（ADR 0000-0014）
├── docs/api-contracts/           # Java 后端真实契约
├── tests/                        # smoke + tools + api + harness + tests/api（GOATS 连通性）
├── docker-compose.yml            # MySQL + LangGraph app
└── .env.example                  # 环境变量模板
```

## 七、常见问题

| 问题 | 处置 |
|------|------|
| `app.main:app` 启动失败 | 检查 `pip install -e ".[dev]"` 是否完成 |
| LangFuse Web 起不来 | 看 `docker compose logs langfuse-web` 是否缺密钥（SALT/ENCRYPTION_KEY/NEXTAUTH_SECRET） |
| 测试 collect error | tests/api 默认已 ignore；如要跑需真实后端 + VPN |
| harness 报 LangFuse 未连接 | 确认 `.env` 的 `ENABLE_LANGFUSE=true` + API Key 已配 |

详见 [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)。
