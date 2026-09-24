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

### 1. 接入层（`app/main.py`、`app/api/`）

- lifespan 初始化 checkpointer 连接池、HTTP 客户端池、日志与 LangFuse；启动时只读校验数据库表结构。
- `POST /v1/workflows/run`：兼容 Dify 协议（ADR 0024 D7）；请求级幂等、不确定回执与对账见 ADR 0026。
- `POST /v1/nodes/prepare`、`POST /v1/nodes/run`：节点级调试接口（ADR 0029）。
- `GET /health`、`GET /ready`（区分硬依赖与软依赖）、`GET /metrics`。

### 2. 图编排层（`app/graph/`）

- `main.py`：`build_main_graph()` 组装主图，三个业务子图以原生子图嵌入。
- `state.py`：`AgentState` 按生命周期分层——本轮输入、会话记忆、业务对象（每轮由 `ingest` 重置）、工程字段（ADR 0024 D2）。
- `safe_node.py` / `retry.py`：写类节点用 `@safe_node`，异常落 `state['error']`；只读 IO 节点用 `@io_node` + `add_io_node` 挂 `RetryPolicy`，写类节点永不自动重试。
- `cascade.py`：出错后的降级路由。

### 3. 子图层（`app/subgraphs/`）

每个业务域一个包：`graph.py`（组装）+ `models.py`（Pydantic 契约）+ 节点文件 + `backend.py`（DTO 构造与后端调用）。

| 子图 | 构成 |
|---|---|
| swap | 意图 / 下单（选对手 ‖ 选标的并行后汇合）/ 确认 / 撤单 / 查单 / 图片与 Excel 多模态；撤单、查单、确认的订单号为确定性提取 |
| option | 1 个意图节点 + 7 个分意图提取节点（ADR 0011）；4 个订单号类节点为确定性提取 |
| close（期权平仓） | 意图 / 平仓（引用解析子图）/ 撤销平仓 / 确认平仓 / 确认撤销 / 持仓查询 / 状态查询 |

### 4. 交易正确性（`app/extraction/`、`app/execution/`、`app/tools/receipts.py`）

- 字段证据契约：模型只输出原文候选与证据，代码校验、归一化并锁定字段（ADR 0027）。
- 最终确认校验：七条确认路径统一由 `app/execution/confirmation.py` 校验"明确动作 + 引用当前订单"（ADR 0021 / 0027）。
- 回执契约：无法验证的回执记为不确定，不推断成功或失败（ADR 0026）。

### 5. 工具与模型（`app/tools/`、`app/llm/`、`app/prompts/`）

- 调用方只依赖 Protocol，禁止直接 `httpx` 调后端（ADR 0001 D2）；类型契约与 Java DTO 一一对应（`models.py`）。
- `llm/clients.py`：全环境统一 DeepSeek-V4-pro，vendor 差异集中适配（ADR 0020）。
- `app/prompts/`：git 是提示词唯一真源；每个 LLM 节点声明一个 `PromptSpec`（ADR 0023）；灰度用同目录并存 + `_versions.yaml`（ADR 0003）。

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

- **写类接口零自动重试**：超时后重试可能重复下单；失败走降级并如实透传后端响应。
- **thread_id = conversation_id**：企微同一会话天然共享状态，checkpointer 按 thread 隔离。
- **标的原文交后端识别**：LangGraph 不维护证券清单（ADR 0025）。
- **单进程部署**：客户私有化最简形态为 1 个应用进程 + MySQL + 自托管 LangFuse。

决策依据见 `docs/adr/`。
