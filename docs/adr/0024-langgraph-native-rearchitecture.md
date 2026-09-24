# ADR 0024 · LangGraph 原生重构：退出 Dify 形态的目标架构

- 状态：已采纳（已冻结：后续决策开新编号）
- 日期：2026-09-17
- 关系：D3 的模型调用与重试边界由 [0031](./0031-single-model-request-per-message.md) 修订；后续拆出 [0025](./0025-instrument-resolution-delegated-to-backend.md) 标的移交后端、[0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) 幂等与回执、[0027](./0027-field-evidence-contract.md) 字段证据、[0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) 入口分流、[0029](./0029-node-level-debug-api-and-regression-workbench.md) 节点层；D8 门槛统一到 [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3
- 作者：图灵科技 + Tony

## 背景

业务链路迁到 LangGraph 后，有四个决定性能力仍是 Dify 形态：

1. **图**：子图靠手写包装调用，无输入 / 输出契约；LangGraph 的 Send / RetryPolicy 等原生能力零使用；多个"厚节点"原样搬自 Dify。
2. **持久化**：checkpoint 只写不读；生产连接无重连；无请求级幂等（重试即可能重复下单）。
3. **可观测**：trace 关联键未生效，LangFuse 无会话 / 用户维度，LLM 指标无数据。
4. **评估**：CI 长期未运行；主力数据集无法被加载；写类链路缺少参数期望。

同时有两条纪律把 Dify 钉成业务真源（"改业务逻辑须先改 Dify"、"冲突选 Dify 原版"）。

## 决策

### D1 · Dify 退出上游：代码即真源

撤销上述两条纪律；Dify 资产打 tag 冻结后移出仓库，同步工具删除；代码注释与测试断言以业务语义为准，而非"与 Dify 一致"。边界：Java operate 契约相关的字段（如 `expected_action` / `place_params`）不属于 Dify 残留，不得按本条清理。

### D2 · State 分层与子图契约

`AgentState` 仍是一个 TypedDict，字段按生命周期分层并由 reducer / 重置规则约束：

| 层 | 典型字段 | 生命周期 |
|---|---|---|
| 本轮输入 | raw_text / quote_content / message_id / input_files | 每轮由 API 唯一入口 `app/api/turn_state.py::inputs_to_state` 写入 |
| 会话记忆 | history_messages（窗口化）、last_confirmed_params（仅作上下文） | 跨轮持久化 |
| 业务对象 | place_params / cancel_params / confirm / close_params / expected_action 等 | **每轮**由 `ingest` 统一重置 |
| 工程字段 | trace / error / trace_id | 每轮重置 |

三个业务子图声明 `output_schema`，只能写回业务对象、意图、回复与 trace / error；父图路由键对子图只读。

### D3 · 图即架构

- 子图以 `add_node(name, compiled_subgraph)` 原生嵌入；厚节点（如平仓、期权询价、render 决策树）拆为小节点或子图，每个分支写 `TraceEntry(decision=)`，错误可归因到具体阶段。
- 互换候选选择共用本轮唯一模型结果，确定性处理可并行，在汇合节点合并。
- **重试边界**：仅独立的后端只读查询用 `@io_node` 挂 `RetryPolicy`，最后一次失败沿原图边收尾；LLM 与写类节点不自动重试，查询重试不得重跑模型。全链路最多一次模型请求的目标约束见 [ADR 0031](./0031-single-model-request-per-message.md)，现有链路待重构。HTTP 客户端为进程级连接池单例。
- 不使用 `interrupt`（[ADR 0021](./0021-text-confirm-replaces-interrupt.md)）。

### D4 · 持久化契约

- checkpointer 使用连接池（回收时间小于 MySQL `wait_timeout`），禁止生产使用单连接形态；`/ready` 探测 checkpointer 自身。
- 生产序列化白名单固化，与测试一致；`durability="exit"`（图内无 interrupt，单轮无需中途恢复）。
- 请求级幂等以企微 `message_id` 为键，详细语义见 [ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md)。
- `history_messages` 窗口化（默认保留最近 40 条，现场以评测校准）。
- Store（跨会话长期记忆）仅在出现明确诉求时引入，不预先建设。

### D5 · 可观测契约

- LangFuse 只有一条请求级注入路径，metadata 携带 `trace_id` / 会话 / 用户 / 环境标签；关闭时 flush。
- LLM 调用指标经 callback 自动采集；节点延迟独立直方图。
- `/ready` 区分硬依赖（MySQL / Java 后端，失败 503）与软依赖（LangFuse / LLM，只标 degraded）。
- 结构化日志（structlog），每条日志自动带 `trace_id` / `conversation_id` / `message_id`。
- `state["trace"]` → `langgraph_node_trace` 与 LangFuse 双轨保留（金融审计与 LangFuse 保留期、可用性假设不同）。
- 脱敏：保留现有可配置脱敏能力，默认关闭；部署位置、字段范围与审计要求明确后另行设计。

### D6 · 评估契约：harness 为唯一门

- CI 在 push / PR 上运行（fast job：ruff + mypy + 一致性 lint + 快速测试；slow job：全量测试 + 真实 MySQL）。
- `harness/` 是唯一评测门（节点层见 ADR 0029）：统一加载各方言数据集；后端业务拒绝单独成桶、不算通过；多轮早停后未执行轮次记失败；`--backend dry-run` 真实生效。
- 写类用例须有 `expected.place_params`；每个线上 P0 / P1 先补数据集用例再修代码。
- 节点公共契约只维护在 `app/node_execution/catalog.py`，应用与 harness 各自决定暴露范围；写节点禁止回放。

### D7 · 协议原生化（暂缓）

原设想新增原生 `POST /v1/runs` 并把 Dify 兼容协议降为临时适配层。本阶段不执行：继续保留 `POST /v1/workflows/run`，Java 源码、配置、`agentUrl` 与 DTO 均不修改。保留 Dify 格式的外部协议不影响内部使用原生 LangGraph 图，也不要求运行时依赖 Dify。

### D8 · 门槛

统一为 ADR 0030 D3 的评测门。无 LLM 密钥的环境只能跑 pytest 与确定性断言，不得替代评测门。

## 当前边界

- 标的识别由 Java 负责，本地不做标的解析；HTTP 输出的 `tickers` 仅为空列表兼容字段（ADR 0025）。
- 业务卡片由 Java 生成：render 透传有效回执；无回执时不得根据本地参数推断交易成功。
- 七条最终确认路径要求当前订单引用与明确动作；跨轮记忆只作上下文，不为裸确认隐式补单号（ADR 0027 D5）。
- 每条消息执行一个业务动作，可携带多笔订单；多动作拆分编排已退役（ADR 0028）。

## 备选方案

- **另起新仓库重写**：丢掉已验证的确定性业务规则与大量数据集素材，且评测台不通电时同样无法证明等价。
- **只做 Dify 清理不动架构**：文件删干净了，但子图包装、只写不读的 checkpoint、假绿的评测台原样保留。
- **先原生化子图再修评测台**：无守护的重构。评测台通电必须先行。

## 后果

- 正面：图、State、持久化、可观测、评估五层各有显式契约；单连接、无幂等等金融正确性风险在首批关闭；Dify 同步类事故不再可能发生。
- 负面：State 分层与子图输出契约让一批隐式跨层写入在类型层暴露，需逐个显式化。
- 未决：`history_messages` 窗口取值的评测校准；`option_close` / `close` 命名统一；Store 是否引入；原生协议迁移时机。
