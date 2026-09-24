# 架构

新人阅读路径：`CLAUDE.md` → 本页 → `CONTEXT.md`（领域语言）→ `docs/adr/README.md`（决策索引）。

本目录描述**现行设计的事实**（"为什么"写在 ADR）：

| 文档 | 用途 |
|---|---|
| 本页 | 单页导览、分层、存储、可观测性与评测概览 |
| [backend-instrument-boundary.md](./backend-instrument-boundary.md) | 标的识别的 LangGraph / Java 职责边界（ADR 0025） |

## 单页导览

```
企微群消息 → Java Worker
    ↓ POST /v1/workflows/run（兼容 Dify Workflow Run 协议，blocking）
FastAPI 接入层（app/main.py + app/api/）
    · 请求级幂等（message_id）· 请求预算与超时快照 · thread_id = conversation_id
    ↓ app/api/turn_state.py::inputs_to_state（一轮输入 → AgentState 的唯一入口）
LangGraph 主图（app/graph/main.py）
    ingest（本轮边界 + 会话过期检查）
      └─ entry_route ─┬─ quick_inquiry            快速询价
                      ├─ existing_command_query   存量兼容
                      └─ pre_route → intent_route（规则优先 → LLM 兜底 → 多轮粘性）
                            ├─ swap 子图          互换
                            ├─ option 子图        期权
                            ├─ option_close 子图  期权平仓
                            └─ fallback           任一节点出错 → 统一降级回复
                         → persist_intent（写回会话意图）
    render → remember_confirmed_params → record_history → persist → END
    ↓
Protocol 客户端（app/tools/）：OptionClient / SwapClient / GoatsAgentClient / MessageClient
    ↓
Java 后端业务接口 → 交易系统（标的识别、业务默认值、订单落库、业务卡片均在后端）

侧翼：MySQL（与 Java 共库，langgraph_ 前缀表）· LangFuse 自托管（trace / 数据集 / 评估）·
      Prometheus /metrics · harness 评测台
```

## 分层

依赖只能自上而下；`tests/test_architecture_layers.py` 守护下列方向（含函数内延迟导入）。

```
接入层      app/main.py · app/api/（HTTP 协议、请求预算、幂等编排）· app/node_execution/（节点调试执行）
               ↓
图编排层    app/graph/main.py（唯一的主图组装入口）
               ↓
业务节点    app/nodes/（主图入口与收尾节点）· app/subgraphs/{swap,option,close}/ + common.py
               ↓            三个子图互不依赖，共用骨架只在 subgraphs/common.py
图基础设施  app/graph/{state,safe_node,retry,cascade,business_params}.py · app/prompts/
               ↓
能力层      app/tools/（Java / GOATS Protocol 客户端与回执）· app/llm/ · app/storage/（MySQL 表与读写）
            app/checkpointer/ · app/observability/
               ↓
规则层      app/domain/（纯业务规则）→ app/extraction/（字段证据框架）→ app/wire_model.py / app/config.py
```

### 1. 接入层（`app/main.py`、`app/api/`、`app/node_execution/`）

- lifespan 初始化 checkpointer 连接池、HTTP 客户端池、日志与 LangFuse；启动时只读校验数据库表结构。
- `POST /v1/workflows/run`：兼容 Dify 协议（ADR 0024 D7）；请求级幂等、不确定回执与对账见 ADR 0026（存储实现在 `app/storage/`）。
- `POST /v1/nodes/prepare`、`POST /v1/nodes/run`：节点级调试接口（ADR 0029）；节点公共契约只在 `app/node_execution/catalog.py`。
- `GET /health`、`GET /ready`（区分硬依赖与软依赖）、`GET /metrics`。
- `api/` 只放 HTTP 层，不直接依赖子图。

### 2. 图编排层与图基础设施（`app/graph/`）

- `main.py`：`build_main_graph()` 组装主图，三个业务子图以原生子图嵌入；这是 `app/graph` 中唯一依赖业务节点的模块。
- `state.py`：`AgentState` 按生命周期分层——本轮输入、会话记忆、业务对象（每轮由 `ingest` 重置）、工程字段（ADR 0024 D2）。
- `business_params.py`：业务对象（place_params / cancel_params / confirm / query_filter / close_params）写入前的形状校验。
- `safe_node.py` / `retry.py`：当前只读 IO 节点用 `@io_node` + `add_io_node` 挂 `RetryPolicy`，写类节点不重试。[ADR 0031](../adr/0031-single-model-request-per-message.md) 已采纳 LLM 零重试与全链路一次请求目标，代码待重构；后端只读查询继续独立重试。
- `cascade.py`：`has_error`，所有条件路由先判错再分流。

### 3. 业务节点（`app/nodes/`、`app/subgraphs/`）

主图节点在 `app/nodes/`，不依赖任何子图内部模块。每个业务域一个子图包：`graph.py`（组装）+ `models.py`（Pydantic 契约）+ 节点文件 + `backend.py`（DTO 构造与后端调用）；三个子图共用 `subgraphs/common.py` 的意图分发路由与 `<product>_unknown` 兜底节点。

| 子图 | 构成 |
|---|---|
| swap | 意图 / 下单（选对手 ‖ 选标的并行后汇合）/ 确认 / 撤单 / 查单 / 图片与 Excel 多模态；撤单、查单、确认的订单号为确定性提取 |
| option | 当前为意图节点 + 分意图节点（一次联合解析目标见 ADR 0031）；询价为「证据提取 → 归一化 → 提交」嵌套子图，其余为确定性代码节点 |
| close（期权平仓） | 意图 / 平仓（引用解析嵌套子图）/ 撤销平仓 / 确认平仓 / 确认撤销 / 持仓查询 / 状态查询 |

### 4. 规则层与交易正确性（`app/domain/`、`app/extraction/`、`app/tools/receipts.py`）

- `app/domain/`：无 IO、无 LangGraph 依赖的纯业务规则，主图节点、子图与客户端共用——
  `order_ids.py`（H- / Q- / CO- / OPT(G)- 形态单一来源）、`numerals.py`（序号与中文数字）、
  `confirmation.py`（七条最终确认路径统一校验"明确动作 + 引用当前订单"，ADR 0021 / 0027）、
  `tenor.py`（期权期限换算）、`fast_execution.py`（最大跟量）、`sanitize.py`（null 字面量清洗）。
- `app/extraction/`：字段证据契约——模型只输出原文候选与证据，代码校验、归一化并锁定字段（ADR 0027）。
- 回执契约：无法验证的回执记为不确定，不推断成功或失败（ADR 0026）。

### 5. 能力层（`app/tools/`、`app/llm/`、`app/prompts/`、`app/storage/`）

- 调用方只依赖 Protocol，禁止直接 `httpx` 调后端（ADR 0001 D2）；类型契约与 Java DTO 一一对应（`models.py`）；机器人上下文统一由 `tools/bot_context.py` 生成。
- `llm/clients.py`：全环境统一 DeepSeek-V4-pro，vendor 差异集中适配（ADR 0020）；各工厂共用 `_build_llm`。
- `app/prompts/`：git 是提示词唯一真源；每个 LLM 节点声明一个 `PromptSpec`（ADR 0023）；灰度用同目录并存 + `_versions.yaml`（ADR 0003）。
- `app/storage/`：`mysql.py`（表名与连接参数，全项目唯一的 MYSQL_URI 解析）、`idempotency.py`（请求幂等）、
  `reconciliation.py`（不确定回执对账）、`node_trace.py`（节点审计写入）。

## 存储

与 Java 共用现有 MySQL 数据库（ADR 0009），全部表使用 `langgraph_` 前缀，由 `sql/init.sql` 初始化：

- checkpoint：`langgraph_checkpoints` / `langgraph_checkpoint_blobs` / `langgraph_checkpoint_writes` / `langgraph_checkpoint_migrations`；清理工具 `scripts/cleanup_checkpoints.py`。
- 业务与审计：`langgraph_message_log`（幂等与回放）/ `langgraph_node_trace`（节点级 trace）/ `langgraph_shadow_compare` / `langgraph_user_feedback`。

## 可观测性

- LangFuse 自托管（`infra/langfuse/`，ADR 0014）：请求级注入 CallbackHandler，trace 携带 `trace_id` / 会话 / 用户。
- Prometheus `/metrics`：HTTP、节点延迟、LLM 调用与 token；告警阈值见 ADR 0019。
- 结构化日志：每条日志自动带 `trace_id` / `conversation_id` / `message_id`。

## 评测

- 数据集：`tests/fixtures/categories/`（验收集）、`tests/fixtures/intent/`（意图集）、`tests/fixtures/nodes/`（节点级）。
- 入口：`python -m harness run`（HTTP 全链路回归）、`python -m harness node-run`（节点回归）、`scripts/langfuse/langfuse_eval.py`（LLM Judge）。
- 放行标准：统一评测门，见 ADR 0030 D3。

## 设计要点

- **每消息最多一次模型请求**：[ADR 0031](../adr/0031-single-model-request-per-message.md) 的目标规范已采纳，当前图仍待重构；上文目录与结构表描述现状，不能据此认为调用额度已经达标。

- **写类接口零自动重试**：超时后重试可能重复下单；失败走降级并如实透传后端响应。
- **thread_id = conversation_id**：企微同一会话天然共享状态，checkpointer 按 thread 隔离。
- **标的原文交后端识别**：LangGraph 不维护证券清单（ADR 0025）。
- **单进程部署**：客户私有化最简形态为 1 个应用进程 + MySQL + 自托管 LangFuse。

决策依据见 `docs/adr/`。
