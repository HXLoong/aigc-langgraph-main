# 架构

新人阅读路径：`CLAUDE.md` → 本页 → `CONTEXT.md`（领域语言）→ `docs/adr/README.md`（决策索引）。

本目录描述**现行设计的事实**（"为什么"写在 ADR）：

| 文档 | 用途 |
|---|---|
| 本页 | 单页导览、分层、存储、可观测性与评测概览 |
| [backend-instrument-boundary.md](./backend-instrument-boundary.md) | LangGraph 提取标的表达，Java 调用识别工作流（ADR 0025） |

## 单页导览

下图与目录说明描述当前代码。[ADR 0026](../adr/0026-request-idempotency-uncertain-receipts-reconciliation.md) 已明确调用端管理消息防重与重投、Java 管理交易幂等，LangGraph 每次合法调用独立处理；现有占位、回放、重投静默和对账尚待清理，进度见 [工作计划](../work-plan.md)。

```
企微群消息 → Java Worker
    ↓ POST /v1/workflows/run（兼容 Dify Workflow Run 协议，blocking）
FastAPI 接入层（app/main.py + app/api/）
    · 请求级幂等（现有实现，待清理）· 请求预算与响应快照 · thread_id = conversation_id
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
Java 后端业务接口（业务默认值、订单数据与状态、业务校验及卡片均在后端）
    · 按业务需要调用对应的标的识别工作流并处理结果
    · 调用交易系统

侧翼：MySQL（与 Java 共库，langgraph_ 前缀表）· LangFuse 自托管（trace / 数据集 / 评估）·
      Prometheus /metrics · harness 评测台
```

## 分层

依赖只能自上而下；`tests/test_architecture_layers.py` 守护下列方向（含函数内延迟导入）。

```
接入层      app/main.py · app/api/（HTTP 协议、请求预算、现有幂等编排待清理）· app/node_execution/（节点调试执行）
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
- `POST /v1/workflows/run`：兼容 Dify 协议（ADR 0024 D7）；当前仍启用可配置的请求占位与响应回放（存储实现在 `app/storage/`），包括失败快照。ADR 0026 是撤除这类消息职责的目标规范，代码尚待调整。
- `POST /v1/nodes/prepare`、`POST /v1/nodes/run`：节点级调试接口（ADR 0029）；节点公共契约只在 `app/node_execution/catalog.py`。
- `GET /health`、`GET /ready`（区分硬依赖与软依赖）、`GET /metrics`。
- `api/` 只放 HTTP 层，不直接依赖子图。

### 2. 图编排层与图基础设施（`app/graph/`）

- `main.py`：`build_main_graph()` 组装主图，三个业务子图以原生子图嵌入；这是 `app/graph` 中唯一依赖业务节点的模块。
- `state.py`：`AgentState` 按生命周期分层——本轮输入、会话记忆、业务对象（每轮由 `ingest` 重置）、工程字段（ADR 0024 D2）。
- `business_params.py`：业务对象（place_params / cancel_params / confirm / query_filter / close_params）写入前的形状校验。
- `safe_node.py` / `retry.py`：当前只读 IO 节点用 `@io_node` + `add_io_node` 挂 `RetryPolicy`，写类节点不重试。[ADR 0031](../adr/0031-single-model-request-per-message.md) 已采纳调用内 LLM 零重试与单次工具调用全链路一次模型请求目标，代码待重构；后端只读查询继续独立重试。
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
  `confirmation.py`（七条最终确认路径识别明确动作、解析引用并校验提交订单号范围，ADR 0021 / 0027）、
  `tenor.py`（期权期限换算）、`fast_execution.py`（最大跟量）、`sanitize.py`（null 字面量清洗）。
- `app/extraction/`：字段证据契约——当前仍有代码数字校验与归一化；ADR 0027 的目标改为保留结构、来源及选择范围检查，由 Java 校验业务值，旧实现待迁移。
- 回执契约：无法验证的回执记为不确定，不推断成功或失败；不确定回执与消息防重是不同职责（ADR 0026，当前代码仍将其用于幂等状态判定，待清理）。

确认职责见 [ADR 0021](../adr/0021-text-confirm-replaces-interrupt.md)：LangGraph 不强制二阶段，识别并提交本次动作、订单号及适用的显式参数；Java 决定业务流程并读取已有订单、合并参数、校验归属 / 权限 / 状态并执行。消息与引用范围校验不等于订单业务校验。当前互换与平仓确认主要提交订单号，期权确认仍从引用与历史拼装完整参数，收敛待办见 [工作计划](../work-plan.md#12-确认指令职责收敛规范已采纳代码待调整)。

### 5. 能力层（`app/tools/`、`app/llm/`、`app/prompts/`、`app/storage/`）

- 调用方只依赖 Protocol，禁止直接 `httpx` 调后端（ADR 0001 D2）；类型契约与 Java DTO 一一对应（`models.py`）；机器人上下文统一由 `tools/bot_context.py` 生成。
- `llm/clients.py`：目标统一 deepseek-v4-pro（本阶段图片暂不处理），配置核对与兼容验证待实施（ADR 0020）；各工厂共用 `_build_llm`。
- `app/prompts/`：git 是提示词唯一真源；每个 LLM 节点声明一个 `PromptSpec`（ADR 0023）；灰度用同目录并存 + `_versions.yaml`（ADR 0003）。
- `app/storage/`：`mysql.py`（表名与连接参数，全项目唯一的 MYSQL_URI 解析）、`node_trace.py`（节点审计写入）；
  `idempotency.py`（请求幂等）与 `reconciliation.py`（不确定回执对账）当前仍在，按 ADR 0026 待清理。

## 存储

与 Java 共用现有 MySQL 数据库（ADR 0009），全部表使用 `langgraph_` 前缀，由 `sql/init.sql` 初始化：

- checkpoint：`langgraph_checkpoints` / `langgraph_checkpoint_blobs` / `langgraph_checkpoint_writes` / `langgraph_checkpoint_migrations`；清理工具 `scripts/cleanup_checkpoints.py`。
- 业务与审计：`langgraph_message_log`（当前用于幂等与回放，后续核对剩余用途及历史记录处置）/ `langgraph_node_trace`（节点级 trace）/ `langgraph_shadow_compare` / `langgraph_user_feedback`。

checkpoint 保存图状态与对话上下文，订单权威数据与业务状态由 Java 管理。确认处理不要求本地保存过该订单；现有持久化配置要求继续有效（ADR 0021 §3）。

## 可观测性

- LangFuse 自托管（`infra/langfuse/`，ADR 0014）：请求级注入 CallbackHandler，trace 携带 `trace_id` / 会话 / 用户。
- Prometheus `/metrics`：HTTP、节点延迟、LLM 调用与 token；告警阈值见 ADR 0019。
- 结构化日志：每条日志自动带 `trace_id` / `conversation_id` / `message_id`。

## 评测

- 现役数据集：`tests/fixtures/biz/`（业务验收集）、`tests/fixtures/intent/`（意图集）。旧节点 fixture 与 B 方言历史参考集已退役；节点执行 API / node-run 保留，Langfuse 节点样本闭环待迁移。
- 入口：`python -m harness run`（HTTP 全链路回归）、`python -m harness node-run`（节点回归）、`scripts/langfuse/langfuse_eval.py`（既有 Judge 路径待移除，过渡期显式 `--no-judge`）。目标为 Langfuse Experiment + 确定性断言闭环（ADR 0005 / 0029）。
- 放行标准：统一评测门，见 ADR 0030 D3。

## 设计要点

- **单次工具调用最多一次模型请求**：[ADR 0031](../adr/0031-single-model-request-per-message.md) 的目标规范已采纳；调用端用同一消息再次调用时独立计数。当前图仍待重构，上文目录与结构表描述现状，不能据此认为调用额度已经达标。

- **调用端管理消息生命周期**：防重、重投与重复通知归调用端，交易执行幂等归 Java；LangGraph 专注本次调用结果（ADR 0026，代码待调整）。
- **调用内交易写接口零自动重试**：超时不证明未执行；失败走降级并如实透传后端响应。
- **thread_id = conversation_id**：企微同一会话天然共享状态，checkpointer 按 thread 隔离。
- **标的原文交后端识别**：LangGraph 不维护证券清单（ADR 0025）。
- **单进程部署**：客户私有化最简形态为 1 个应用进程 + MySQL + 自托管 LangFuse。

决策依据见 `docs/adr/`。
