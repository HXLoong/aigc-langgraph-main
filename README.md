# OTC Agent · 场外衍生品 AI 指令助手

基于 FastAPI 与 LangGraph 的企微指令解析服务，支持互换、期权和期权平仓。
服务通过 Dify 兼容 HTTP 接口接收消息，将解析结果提交 Java 业务接口并返回业务回复。
MySQL 提供会话持久化与审计，Langfuse 提供可选追踪。

## 启动命令

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

服务启动后，检查接口并运行 app 核心测试：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false \
  python -m pytest tests/test_smoke.py -q
```

## 部署说明

运行环境为 Python 3.11+。生产持久化使用 MySQL 8.0.19 至 9.6.0 之前的版本。
数据库初始化前，将 `MYSQL_URI` 指向 Java 现有数据库；初始化脚本创建 LangGraph 使用的表，不创建数据库。
生产服务启用 `USE_MYSQL_CHECKPOINTER=true`。无数据库本地调试设置
`ENVIRONMENT=development`、`USE_MYSQL_CHECKPOINTER=false`、`MYSQL_URI=""`。
仅关闭 checkpoint 不会关闭已配置 URI 的节点审计。

`.env` 中需要配置以下项目：

| 配置 | 用途 |
|---|---|
| `LLM_PROVIDER`、`LLM_API_BASE`、`LLM_API_KEY` | 模型适配、网关地址与凭证 |
| `LLM_MODEL_STANDARD`、`LLM_MODEL_THINKING`、`LLM_MODEL_COMPLEX` | 必填模型角色名称，业务解析使用 STANDARD |
| `OTC_API_BASE_URL`、`OTC_API_SECRET` | Java 业务接口与凭证 |
| `GOATS_BASE_URL`、`GOATS_CLIENT_ID`、`GOATS_CLIENT_SECRET`、`GOATS_EXTAPP_SALT` | 快速询价与存量查询接口 |
| `MYSQL_URI`、`USE_MYSQL_CHECKPOINTER` | 数据库连接与会话持久化 |
| `ENABLE_LANGFUSE`、`LANGFUSE_*` | 可选追踪与平台记录 |
| `EVAL_USER_ID`、`EVAL_ROOM_ID` | 黄金集评测的授权测试账号与群 |

已有 `.env` 时保留原配置。密钥不得提交仓库。完整开发配置见
[开发指南](./docs/development/README.md)，数据库初始化见 [`sql/init.sql`](./sql/init.sql)。

## 服务接口

| 入口 | 用途 |
|---|---|
| `http://127.0.0.1:8000/docs` | HTTP 接口文档 |
| `GET /health` | 服务存活检查 |
| `GET /ready` | 依赖状态检查 |
| `POST /v1/workflows/run` | Dify 兼容业务入口 |
| `POST /v1/nodes/run` | 受保护的节点调试入口 |

普通业务输入须传入 `robotVersion: "V2"`。缺省版本按 V1，普通消息静默。
请求中的账号、群和消息 ID 使用调用端真实身份。单次调用处理一个业务动作，可包含多笔订单。
证券识别与交易业务校验由 Java 负责。入口分流见
[主图流程](./docs/architecture/main-graph-flow.md)。

## 测试与评测

app 核心测试验证路由、状态、参数、字段来源、引用选择、错误兜底与 HTTP 契约。
改动验证运行受影响的测试文件，完整验收运行 `python -m pytest tests/ -q`。

黄金用例保存在 [`tests/datasets/`](./tests/datasets/README.md)，统一由 Harness 请求已启动的
`http://127.0.0.1:8000` 服务。Harness 不启动 app，不修改服务配置，不连接数据库准备测试消息。

```bash
python -m harness run --group intent --backend mock
python -m harness run --file tests/datasets/biz/swap_prod.jsonl \
  --case ai_trade_assist_prod_swap_order_case_1 --backend java
```

`--group biz|intent|all` 选择数据集，`--file` 选择文件，`--case` 选择用例；文件和用例参数可重复。
`--backend mock|java` 声明评测后端，运行中的 app 须已配置对应接口。
默认范围为业务集全量。Java 评测须使用已授权账号与数据，不随部署自动执行。
mock_api 替代外部接口，不模拟模型。Python 同步判定结果，不依赖 Langfuse 或 Node.js。

评分规则、报告与 mock 服务配置见 [测试指南](./docs/testing/README.md) 和
[Harness 说明](./harness/README.md)。

## 项目结构与文档

| 目录 | 内容 |
|---|---|
| `app/` | HTTP 服务、图、业务节点、解析契约、客户端与提示词 |
| `harness/` | 黄金集加载、HTTP 执行、确定性评分与报告 |
| `tests/` | app 核心测试与黄金数据集 |
| `mock_api/` | 本地外部接口 stub |
| `scripts/` | 数据同步、部署与运维 |
| `infra/`、`sql/` | 基础设施配置、数据库初始化与迁移 |

- [开发指南](./docs/development/README.md) · 环境配置、接口调用与日常开发
- [测试指南](./docs/testing/README.md) · 核心测试、黄金集范围与评分
- [架构导览](./docs/architecture/README.md) · 代码分层与图结构
- [领域术语](./CONTEXT.md) · 业务概念与职责边界
- [Java 接口契约](./docs/api-contracts/java-backend.md) · 出站业务协议
- [部署文档](./docs/deploy/README.md) · 服务部署与环境检查
- [运维手册](./docs/operations/on-call-runbook.md) · 监控与故障处置
- [ADR](./docs/adr/README.md) · 架构决策
- [文档地图](./docs/README.md) · 文档索引

## License

Internal — 图灵科技
