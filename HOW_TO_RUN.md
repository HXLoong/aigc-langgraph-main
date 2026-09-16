# HOW TO RUN — 场外衍生品 AI 指令助手

本目录 `aigc-langgraph`（LangGraph 智能代理）。

> 当前阶段：M1 / M2 / M3.1 / M3.2 完成 → M3.3 真后端 golden 回归 + 现场 sign-off 进行中（issues #82–#87）；M4 灰度工具链已就绪。本文档反映当前 main 分支状态。

## 一、架构概览

```text
企微消息 → Java Worker → POST /v1/workflows/run → LangGraph (8000) → LLM 意图解析 / 参数提取
                                                          ↓
                                                LangFuse (3000 self-hosted 或 Cloud) — trace / dataset / eval / annotation
                                                          ↓
                                         MySQL (3306) — checkpoint + 业务库
                                                          ↓
                                          Java Backend（option / swap / GOATS ticker）
```

## 二、依赖

| 依赖 | 用途 |
|------|------|
| Docker Desktop | MySQL + LangFuse stack 容器 |
| Python 3.11+ | LangGraph FastAPI + harness CLI + scripts/* |
| 公网 | LLM 调用（DashScope / Anthropic Judge）；客户现场走 Qwen API 直连 |

不再需要 Java 后端 Mock，M3 阶段直接对接真实后端（含 GOATS）。

## 三、启动流程

### 1. 环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填：
#   QWEN_API_KEY      （阿里云 DashScope）
#   ANTHROPIC_API_KEY （评估 Judge 用，可选）
#   OTC_API_BASE_URL  （真后端地址 / 客户现场 admin-api）
#   GOATS_*           （ticker 校验）
```

### 2. 启动 MySQL

```bash
docker compose up -d mysql
```

### 3. 启动 LangFuse self-hosted（ADR 0014）

> M3 阶段评估脚本默认写到 **Langfuse Cloud**（`us.cloud.langfuse.com`），如不需要本地 stack 可跳过本步骤。

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
LANGFUSE_HOST=http://localhost:3000      # 或 https://us.cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### 4. 启动 LangGraph（端口 8000）

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

验证：

```bash
curl http://localhost:8000/health     # liveness
curl http://localhost:8000/ready      # readiness
curl http://localhost:8000/metrics    # Prometheus exposition
```

## 四、验证

### 健康检查

```bash
curl http://localhost:8000/health        # LangGraph
curl http://localhost:3000/              # LangFuse UI（self-hosted）
docker ps --filter "name=otc-agent" --filter "name=langfuse"
```

### 单元测试

```bash
pytest tests/ -v                 # 1864 passed + 15 skipped（约 3 分钟）
pytest tests/test_smoke.py -v    # 仅 smoke（图编译 + 端到端 stub run + @safe_node 异常捕获）
pytest -k "not e2e"              # 跳过端到端
pytest --lf                      # last-failed
```

> `tests/api/` 是 GOATS 接口连通性测试，需真实后端 + VPN，已通过 pyproject `addopts = "--ignore=tests/api"` 默认跳过；M3 现场联调时手动 `pytest tests/api/`。

### 评估入口（M3 阶段主用）

**A · DeepSeek Judge 评估（推荐，含 per-turn 富集 JSON 写回 Langfuse Cloud）**：

```bash
# 全量（现役数据源 tests/fixtures/categories，350+ 条）
python scripts/langfuse_eval.py --local tests/fixtures/categories --concurrency 4

# 指定 case 子集
python scripts/langfuse_eval.py --local tests/fixtures/categories --ids case-025,case-026 --concurrency 2

# Langfuse Dataset 模式（运行后到 UI 看 score + judge_comment + turns[i] 富集字段）
python scripts/langfuse_eval.py --concurrency 4
```

跑完后 stdout 会输出 `LangFuse 写入成功  run=local-YYYYMMDD-HHMMSS`，到 Langfuse UI 按 run name 过滤即可逐条查错（详见 CLAUDE.md "排查与修复流程"）。

**B · 纯本地 harness（快速 smoke，无 Judge）**：

```bash
python -m harness doctor                  # 环境体检（/health /ready）
python -m harness run                     # 跑 fixture（默认 tests/fixtures/categories/）
python -m harness run --case case-025     # 单 case
```

**C · 上传 golden 到 Langfuse Dataset（同步工具）**：

```bash
python scripts/upload_golden_to_langfuse.py   # tests/fixtures/categories/ → Langfuse Dataset
```

### 真后端 e2e 探针（M3 联调用）

```bash
python scripts/probe_real_backend_e2e.py    # 通用连通性 / 健康检查
python scripts/probe_swap_write_e2e.py      # swap 写路径
python scripts/probe_option_write_e2e.py    # option 写路径
python scripts/probe_close_write_e2e.py     # close 写路径
python scripts/probe_ticker_e2e.py          # ticker 子图
```

### M4 灰度上线工具链（已就绪，可直接复用）

```bash
# 一键部署 + smoke 自检（客户现场）
bash scripts/deploy-customer.sh

# 演练 smoke（F4.0）
bash scripts/drill_smoke.sh

# Shadow 双跑：LangGraph vs Dify 字段级 diff（M4 第二意见）
python scripts/shadow_compare.py            # 含 DRY_RUN_BACKEND 模式（PR #112）

# 金丝雀状态 + F4 全指标快照
python scripts/canary_status.py
python scripts/metrics_snapshot.py

# LangFuse Prompt 晋升（staging → production，F4.6）
python scripts/promote_langfuse_prompt.py

# 告警阈值干跑（5xx / cascade / P95 延迟 / LLM 失败率）
python scripts/run_alerts.py

# 紧急回切（企微管理员改 Webhook + 应用层兜底）
bash scripts/rollback_canary.sh

# Grafana 灰度观测面板 JSON 模板：见 infra/ 目录（F4.2-F4.5）
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
| LangFuse Web（self-hosted，可选） | 3000 | `docker compose -f infra/langfuse/docker-compose.yml ... up -d` |
| LangFuse Worker（self-hosted，可选） | 3030 | 同上（一并启动） |
| LangGraph FastAPI | 8000 | `uvicorn app.main:app --port 8000 --reload` |

## 六、目录结构

```text
aigc-langgraph/
├── app/                          # LangGraph 应用层
│   ├── main.py                   # FastAPI 入口 + HTTPMetricsMiddleware + /metrics
│   ├── api/                      # routes.py + health.py
│   ├── graph/                    # state + safe_node + cascade fallback
│   ├── graphs/main_graph.py      # 主图组装 + 一级路由
│   ├── nodes/                    # ingest / intent_route / persist / render / fallback
│   ├── subgraphs/                # swap / option / close / ticker（共 20 节点）
│   ├── tools/                    # OptionClient / SwapClient / TickerClient + models
│   ├── llm/clients.py            # Qwen 工厂（standard / thinking / VL / 35b-a3b）
│   ├── checkpointer/factory.py   # AIOMySQLSaver
│   ├── observability/            # tracing + metrics（/metrics 端点）
│   └── prompts/                  # Dify 提示词资产
├── harness/                      # 评测台 CLI
├── infra/langfuse/               # LangFuse self-hosted compose
├── docs/adr/                     # 20 个架构决定（ADR 0000-0019）
├── docs/api-contracts/           # Java 后端真实契约
├── scripts/                      # langfuse_eval / probe_* / upload_* / canary_* 等
├── tests/                        # 1864 passed + 15 skipped
├── tests/fixtures/               # golden.jsonl（350+）+ golden_ticker_2026-05.jsonl
├── docker-compose.yml            # MySQL + LangGraph app
└── .env.example                  # 环境变量模板
```

## 七、常见问题

| 问题 | 处置 |
|------|------|
| `app.main:app` 启动失败 | 检查 `pip install -e ".[dev]"` 是否完成 |
| LangFuse Web 起不来 | 看 `docker compose logs langfuse-web` 是否缺密钥（SALT / ENCRYPTION_KEY / NEXTAUTH_SECRET） |
| 测试 collect error | tests/api 默认已 ignore；如要跑需真实后端 + VPN |
| harness 报 LangFuse 未连接 | 确认 `.env` 的 `ENABLE_LANGFUSE=true` + API Key 已配 |
| `scripts.llm_cost_report` ImportError | 已修：pyproject `pythonpath = ["."]`，重新 `pip install -e .` 即可 |

详见 [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) 与 [docs/troubleshooting-sop.md](./docs/troubleshooting-sop.md)。
