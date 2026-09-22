# ADR 0024 · LangGraph 原生重构：退出 Dify 形态的目标架构与分阶段路线

- 状态：**已采纳并修订**（2026-09-22：标的识别委托后端；重试收尾与节点目录收敛；强制脱敏及原生协议迁移暂缓）
- 日期：2026-09-17
- 起源：用户要求"拉取最新 main，评估代码是否按 LangGraph 特性（checkpoint、共享 state、golden、LangFuse）开发，目的是彻底改造以前 Dify 的实现，用全新 LangGraph 架构做彻底重构"。评估报告：[docs/langgraph-architecture-assessment.md](../langgraph-architecture-assessment.md)
- 修订：[ADR 0000](./0000-migrate-from-dify-to-langgraph.md) 后果段"需要长期维护 Dify YAML 同步工具、让业务方继续用 Dify UI 调整提示词"（**被取代**：Dify 不再是上游）；[ADR 0001 D3](./0001-rewrite-app-with-harness-first.md)"完全模拟 Dify Workflow Run API……跑稳后如需干净协议另开 ADR"（**本 ADR 即该 ADR**）；[ADR 0001 D6](./0001-rewrite-app-with-harness-first.md)（AgentState 分层）；[ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md)（saver 连接与 CI 覆盖）；[ADR 0014](./0014-langfuse-as-harness-backend.md) D7（trace 关联键在生产必须生效）；沿用 [ADR 0021](./0021-text-confirm-replaces-interrupt.md)（文本二阶段确认）与 [ADR 0023](./0023-prompt-as-code-langgraph.md)（PromptSpec）
- 作者：图灵科技 + Tony


## 当前边界修订（2026-09-22）

本 ADR 的 State、并行、RetryPolicy、回执及可观测性决策继续有效。现役边界如下：

- 标的识别迁至 Java，删除本地 ticker 子图。LangGraph 保留证券原文与引用选择，`tickers` 仅作空列表兼容字段；不据此判断零命中或生成消歧卡。见[标的识别后端边界](../backend-instrument-boundary.md)。
- 业务卡片由 Java 生成。render 透传有效回执；业务码 500 仅投影展示文案，原始码和结果保留。无回执时不得根据本地参数推断交易成功。
- 七条最终确认路径要求当前订单引用及明确动作；跨轮记忆只作上下文，不再为裸确认隐式绑定单号，也不拼接确认请求。
- 每条消息按产品与意图优先级执行一个业务动作，可携带多笔订单；多动作拆分、依赖编排与批次调度已删除，节点执行接口和评测目录同步移除对应注册。历史幂等回执仍可原样重放，不重新执行业务。

下文日期化落地记录保留历史事实；其中 ticker 子图、节点计数和确认记忆回退均需按上述修订理解。

## 上下文

DSL v2 迁移（2026-08）后，代码在 LangGraph 上跑通了全部业务链路，但评估显示它在四个决定性能力上仍是 Dify 形态（详见评估报告第一节评分卡）：

1. **图**：子图靠手写 `ainvoke` + `Overwrite` 包装，无 input / output schema，1.x 的 Command / Send / RetryPolicy / durability 零使用；ticker 12 步管线是"Python 写的图"；`render` / `place_close` / `extract_inquiry` 是 Dify code 节点原样搬来的厚节点。
2. **持久化**：checkpoint 除 `history_messages` 外只写不读；生产 saver 单连接无重连；无请求级幂等（重试即重复下单）；serde 未固化；`history_messages` 无界。
3. **可观测**：生产走裸 `CallbackHandler`，trace_id 契约是死码；LangFuse 无 session / user；LLM 指标零调用导致告警永不触发；敏感字段明文。
4. **评估**：CI 自 2026-05-12 不跑；主力 921 条数据集被主力加载器拒绝；`windCode` 别名 bug 让仅有的节点级期望恒假失败；写类链路零 `place_params` 期望。

同时，两条现行纪律把 Dify 钉成业务真源：`app/nodes/route_rules.py:8`"改业务逻辑必须先改 Dify 源再同步"、`.claude/rules/git-workflow.md`"提示词冲突永远选 Dify 原始版本"。ADR 0022 已把 git 定为提示词真源，但代码与流程层的这两条没有同步撤销。

## 决策

### D1 · Dify 退出"上游"地位：代码即真源，Dify 资产冻结为历史参照

- 撤销"改业务逻辑必须先改 Dify 源再同步"与"冲突永远选 Dify 原始版本"；dify/yaml/ 与 docs/archive/dify-originals/ 冻结（已打 tag `dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建）` 后移除，见附录 C 级与落地记录）。
- 代码注释里"与 Dify 对齐 / 1:1 移植 / 同口径"的表述改写为业务语义陈述；测试断言以业务正确性而非"与 Dify 一样"为口径。
- **边界**：`expected_action` / `place_params` / `confirm_modify_order` 等是 **Java 后端 operate 契约与 ADR 0001 D5 节点合并**的产物，不属 Dify 残留，不得按本决策清理。A 级保留清单见附录。

### D2 · State 分层与子图契约

`AgentState` 按生命周期分层（仍是一个 TypedDict，但字段按层分组并由 reducer / 重置规则约束）：

| 层 | 字段 | 生命周期 |
|---|---|---|
| TurnInput | raw_text / quote_content / message_id / input_files / fast_query / at_bot / … | 每轮由 API 全量写入；缺省显式置空（单一位置） |
| ConversationMemory | history_messages（**窗口 reducer**，保留最近 N 轮或 token 预算）、last_confirmed_params（上一轮已确认订单号，仅作上下文） | 跨轮持久化 |
| BusinessObjects | tickers / place_params / cancel_params / confirm / query_filter / close_params；`expected_action` 提升为顶层 `Literal["place","modify","cancel","inquiry","close"]` | **per-turn**：ingest 统一重置，render 不得读上一轮残留 |
| Engineering | trace（per-turn）、error、trace_id | 每轮重置 |

- 三个业务子图声明 `output_schema`：只允许写回 BusinessObjects + intent + reply / api_* + trace / error；父图路由键（`product_type` / `swap_input_mode`）对子图只读。ticker 子图已于 2026-09-20 退役；HTTP tickers 保持空列表，不作为识别结果。
- 一轮的边界只在一个位置维护（`ingest`），删除 `_reset_turn_trace` 与 API 层 `setdefault` 清理。

### D3 · 图即架构：原生子图、Send 并行、RetryPolicy

- 子图用 `add_node(name, compiled_subgraph)` 原生嵌入，删除 `_as_subgraph_node`。
- 历史 ticker 原生子图已于 2026-09-20 退役：LangGraph 保留标的原文与引用选择，由 Java 业务接口负责识别和权威校验，见[标的识别边界](../backend-instrument-boundary.md)。
- swap 选对手 ‖ 选标的并行：`place_params` 按 order_index 合并的 reducer，或拆 `counterparty_picks` / `ticker_picks` 两通道 + join 节点。
- `place_close`（6 阶段）、`render`（18 分支）、`extract_inquiry`（3 管线）拆为小节点或表驱动；每个分支写 `TraceEntry(decision=)`。
- IO 节点（LLM / 后端）挂 `RetryPolicy`，由框架调度尝试。`add_io_node` 通过 `Runtime.execution_info.node_attempt` 在最后一次可重试失败时返回 ErrorInfo，沿原节点出边完成 cascade、并行汇合和父图回复/审计；不再依赖没有原出边的独立 error handler。`with_error_handler=False` 保留耗尽后抛异常的语义。写类节点不重试。HTTP 客户端为 lifespan 单例，协议层吃 `BotContext`。
- 继续不用 `interrupt`（ADR 0021）；若未来企微侧支持回调确认，再评估 `interrupt` + `Command(resume)`。

### D4 · 持久化契约（金融正确性）

- saver 使用 `aiomysql` 连接池（`pool_recycle` 小于 MySQL `wait_timeout`），`from_conn_string` 单连接形态禁止用于生产；`/ready` 的 mysql 探针改为打 saver 自身。
- 生产 serde 固化：`JsonPlusSerializer(allowed_msgpack_modules=[("app.graph.state", "TickerCandidate"|"Message"|"TraceEntry")])`，与测试一致。
- `durability="exit"`：图内无 interrupt，单轮无需中途恢复；写路径（下单 / 平仓 / 确认）提交后端前是否额外落盘，由后续阶段按幂等设计裁决并记录。
- 请求级幂等：路由层以 `(conversation_id, message_id)` 去重，启用 `message_log.uk_message_id`，冲突即回放上一次 `reply_text`，不重跑图；`node_trace` 加幂等键；schema 演进引入 alembic。
- `history_messages` 窗口化；七条最终确认路径均须引用当前订单并明确确认动作，经 `app/execution/confirmation.py` 校验范围。`last_confirmed_params` 仅作上下文，不能替代引用或自动补足最终确认单号。
- CI 增加 MySQL service，至少一条 `AIOMySQLSaver` 真实多轮用例。
- Store：仅当出现"同一客户跨群偏好"类诉求时引入，不预先建设。

### D5 · 可观测契约

- 单一请求级注入路径：删除图级 `_attach_langfuse_callbacks` 与 `environment == "development"` 分叉；`config.metadata` 携带 `trace_id` / `langfuse_session_id=conversation_id` / `langfuse_user_id` / `langfuse_tags=[environment, product…]`；`Langfuse(environment=)`。
- LLM 指标接 callback（`on_llm_end` / `on_llm_error` → `emit_llm_call` / `emit_llm_tokens`，节点名取 `metadata["langgraph_node"]`），独立 `otc_agent_node_latency_ms{node}` 直方图。
- 脱敏（2026-09-22 裁决，#221）：保留现有 `Langfuse(mask=)` 和日志字段配置，默认关闭；暂不增加 TraceEntry 强制脱敏或改变审计原文。实际部署位置、字段范围和审计要求明确后另行设计。ENABLE_LANGFUSE 默认关闭，不能仅凭脱敏开关推断有数据出境。
- `/ready` 区分硬依赖（mysql / java 后端）与软依赖（langfuse / llm）；软依赖失败只进 body。
- structlog + `trace_id` contextvar；lifespan 关闭段 `flush`。
- `state["trace"]` → `node_trace` 双轨**保留**（金融审计与 LangFuse 保留期 / 可用性假设不同），只修口径与脱敏。
- 暂不引入 `astream_events`（上游 Java 写死 blocking）。

### D6 · 评估契约：harness 唯一 gate

- CI 恢复 push / PR 触发（fast job < 2 min：ruff + fixture lint + ADR lint + `pytest -k "not e2e"`；慢 job 全量）。
- `harness/` 为唯一 gate：并入 B 方言（`conversation[]`）加载器，可执行样本 389 → 1310、多轮 9 → 260；修 `windCode`；业务拒绝不算 PASS（单独桶）；早停后未执行轮次显式记失败；`--backend dry-run` 真生效。`scripts/langfuse/langfuse_eval.py` 降为 Judge + LangFuse 上报薄层，`scripts/ai_test_langgraph/` 标 deprecated。
- 写类 case 必须有 `expected.place_params`（从 `response_contains` 反向生成后人工抽检），fixture lint 守护；Judge 阈值 0.9 + 中间档定义；每个线上 P0/P1 先补 fixture 再修代码。
- D 桶：`annotation_source` / `captured_at` / `redacted` 字段 + LangFuse trace → fixture 的反向脚本（新增于 `scripts/`）。

**2026-09-22 执行范围与节点目录修订（#220 / #224）**：本轮先完成代码修复；结构化标注后续按现役 categories 的关键写入场景和实际业务对象开展，经业务审核后纳入验收，不把历史 unified 的 560 条直接纳入本轮。运行结果只能作为标注草稿，不能直接充当标准答案。

公共节点契约只在 `app/node_execution/catalog.py` 维护节点身份、调用位置、输入输出字段、副作用与暴露范围。应用负责 State schema、执行工厂及客户端注入；harness 负责展示、标注和回放策略。二者可有不同暴露范围，不能用整表集合相等代替共享契约校验；写节点禁止回放，重试资格与回放权限分别表达。目录导入不加载配置或业务节点。

### D7 · 协议原生化（本阶段暂缓，#222）

- 原设想为新增 `POST /v1/runs` 与类型化请求/响应，将 Dify 形态改为临时 adapter 后退役；该迁移本阶段不执行，不列为当前验收缺口。
- 持续保留 `POST /v1/workflows/run`，维持 Java 请求、响应、状态码及会话契约。Java 源码、配置、agentUrl 和 DTO 均不修改，不安排 Java 切换或旧协议删除。
- 若以后需要整理 Python 内部协议转换，可在不改变外部契约的前提下另行实施。保留 Dify 格式不影响内部使用 LangGraph 原生图，也不要求运行时依赖 Dify。

### D8 · 分阶段与门槛

| 阶段 | 内容 | 门槛 |
|---|---|---|
| 0 通电与止血（1-2 周） | CI；`windCode`；saver 池 + serde + 探针；幂等；`durability="exit"`；LangFuse 维度 + 注入统一；LLM 指标；`/ready` 软硬分离；`record_history` safe_node；撤销两条 Dify 纪律；revoke 明文 key | pytest GREEN；6 条 winners 期望真实通过；CI 在 PR 上跑 |
| 1 State 契约（2-3 周） | B 方言并入；`expected.place_params`；Judge 兜底与阈值；State 分层 + output schema；history 窗口；per-turn 重置；`make_initial_state` 退役；`expected_action` 顶层 | eval PASS ≥ 阶段 0；子图改父图路由键在类型级不可能 |
| 2 子图原生化（3-4 周） | 原生嵌入；并行；拆厚节点；RetryPolicy；客户端单例；协议层解耦（ticker 识别现已委托后端） | trace 每步可归因；节点延迟直方图有数据；eval ≥ 阶段 1 |
| 3 协议原生化 + Dify 退役（原计划，部分暂缓） | 协议迁移与 Java 切换暂缓；其余元数据 / 死 `[user]` / 占位符清理、测试口径与文档按各自范围执行 | 保持现行 Java 契约；协议迁移另行裁决 |
| 4 持续 | D 桶；覆盖矩阵；多模态样本；Store（按诉求） | 事故先补 fixture |

每阶段的 eval 门在真 LLM + mock/dry-run 后端上跑；无 LLM 密钥的环境只能跑 pytest 与确定性 harness 断言，不得代替 eval 门。

## 备选方案

- **推倒重写一个新仓库**：丢掉已验证的业务规则（prewash / aggregate / reference_parser / sanitize 等确定性层）与 2700+ 条素材；且评估台不通电时新仓库同样无法证明等价。否决。
- **只做 Dify 清理不动架构**：注释与文件删干净了，但子图包装、只写不读的 checkpoint、无 session 的 LangFuse、假绿的评估台原样保留，"彻底重构"名不副实。否决。
- **先做子图原生化再修评估台**：无守护的重构，评估报告第五节已证明现役集守不住 `place_params` 与多轮。否决，评估台通电必须是阶段 0。

## 后果

- 正面：图、State、持久化、可观测、评估五层各有一份显式契约；金融三条 P0（单连接 saver、无幂等、敏感字段出境）在阶段 0 关闭；Dify 从"上游真源"变为历史参照，后续同步事故（SW-INC-01 类）不再可能发生。
- 负面：阶段 1-3 约 8-10 周工程量；阶段 3 需 Java 侧联调发版；State 分层与子图 output schema 会让一批"子图顺手改父图字段"的隐式行为在类型层暴露，需要逐个显式化。
- 未决：写路径提交前的 durability 裁决（与幂等设计一起在阶段 1 记录）；`history_messages` 窗口 N 的取值需 eval 校准（机制已落地，默认 40）；`option_close` / `close` 命名统一方向；Store 是否引入。

## 落地记录（按日期保留历史；当前边界见文首）

2026-09-17 条目保留为当时记录；其中 ticker、本地卡片、记忆补单号及独立 error handler 的现役状态以本篇 2026-09-22 修订为准。

- 2026-09-17 阶段 0 首批（本 ADR 同一 PR，TDD）：`harness/differ.py` `windCode` 修正 + 真实 `TickerCandidate` 契约测试；`record_history` 加 `@safe_node`；`AgentState.reply_text` 重复声明清理、`api_result` 类型改为 `str | dict | list | None`；`_build_run_config` 增加 `langfuse_session_id` / `langfuse_user_id` / `langfuse_tags`；`graph.ainvoke(..., durability="exit")`；生产 saver `serde` 白名单固化；`tracing.py` 客户端注册顺序修正；撤销 `route_rules.py` 与 `git-workflow.md` 两条"Dify 为真源"纪律。其余阶段 0 项（CI 触发恢复、saver 连接池、请求级幂等、LLM 指标 callback、`/ready` 软硬分离、revoke 明文 key）需团队决策或真实 MySQL 环境，列为待办。
- 2026-09-17 重构 1（D2 / D3，TDD）：`TraceEntry` / `Message` 增加不参与 dump 与相等比较的 `id`，`trace` / `history_messages` 的 reducer 由 `operator.add` 改为 `merge_by_id`（与 LangGraph `add_messages` 同款按 id 去重）；新增 `SubgraphOutput` TypedDict，三个业务子图 `StateGraph(AgentState, output_schema=SubgraphOutput)`，子图对 `product_type` / `swap_input_mode` / `history_messages` / 入口字段的写入停在子图内；主图改为 `add_node(name, compiled_subgraph)` 原生嵌入，删除 `_as_subgraph_node`。实验（`tests/graph/test_reducers.py` / `test_subgraph_contract.py`）证实：原生子图节点回传完整输出 state，`operator.add` 会把父图已有 trace 再加一遍，按 id 合并后零重复；`_reset_turn_trace` 暂留（一轮边界收敛到 ingest 待下一步）。
- 2026-09-17 重构 2（D3，TDD）：ticker resolver 变真子图 ~~`app/subgraphs/ticker/graph.py`~~——私有 `TickerState`，`extract_candidates` → 三路 LLM 并行分支（`infer_codes` ‖ `split_keywords` ‖ `judge_type`）→ `merge_candidates` → `Send` 按 orgStr fan-out `resolve_org_item`（GOATS + rank，此前串行）→ `assemble` 按输入 index 汇总；`compile(checkpointer=False)` 不继承父 checkpointer；节点函数留在 `resolver.py`（测试 monkeypatch 边界不变），`resolve_ticker_full()` façade 契约不变。~~`tests/subgraphs/ticker/test_graph.py`~~ 断言拓扑与并发峰值 ≥ 2。
- 2026-09-17 重构 3（D3，TDD）：swap 选对手 ‖ 选标的 并行——两个 LLM 节点只产出指针到 `swap_counterparty_picks` / `swap_ticker_picks`（AgentState 新增两通道），确定性查表覆盖收敛到新汇合节点 `swap_apply_picks`（用后清空通道）；`_route_after_place_order` 返回并行分支列表，两条边汇合到 `swap_apply_picks` 再路由提交 / 兜底。热路径少一次串行 LLM 往返；`place_params` 保持单值覆盖语义，不引入 dict 合并 reducer。
- 2026-09-17 重构 4（D3，TDD）：`render` 18 分支决策树每个出口写 `TraceEntry(node="render", decision=…)`（`passthrough` / `api_result` / `hitl_card` / `zero_match` / `error:*` / `unknown_*` / `close_card` / `cancel_ack` / `no_reply` 等），回复文本零变化；eval 失败归因不再看不到 render 走了哪条分支。
- 2026-09-17 重构 5（D3，TDD）：`close_place_close` 215 行 6 阶段厚节点拆成子图 `build_place_close_graph()`：`place_close_parse` → `fetch_orders` → `extract`（LLM）→ `normalize`（合并 + 确定性后处理）→ `validate` → `submit` / `reject`，两处早退（空列表、校验失败）做成图边，每阶段一条 TraceEntry，错误归因到具体阶段（如 `place_close_extract`）；私有 `PlaceCloseState`（AgentState + `pc_*` 中间态）+ `PlaceCloseOutput` output_schema，中间态不外泄；close 图 `add_node("close_place_close", build_place_close_graph())` 原生嵌入；`close_place_close(state)` façade 契约不变，汇总条目沿用 `close_place_close` 名兼容既有归因。
- 2026-09-17 重构 6（D2，TDD）：业务对象 per-turn 语义落地——评估核实没有任何业务节点把上一轮的 `tickers` / `place_params` / `cancel_params` / `confirm` / `query_filter` / `close_params` 当结果读（唯一读者是 render，残留会被渲染成"已收到撤单请求"），`ingest` 统一清空这些字段与 `ticker_hitl_candidates` / swap 指针通道；一轮的边界收敛到 `ingest`（`trace` 用 `Overwrite([])` 重置，`@safe_node` 学会把自身条目写进 Overwrite），删除主图 `_reset_turn_trace` 节点；跨轮记忆只保留 `history_messages`。API 层对当轮输入字段的显式置空保留（输入必须由请求决定，不属于图内边界）。
- 2026-09-17 重构 7（D4，TDD）：`history_messages` 窗口——reducer 改为 `merge_history`（按 id 合并后只保留最近 N 条），N 走 `Settings.history_window_messages`（默认 40 条 ≈ 20 轮，`.env.customer.template` 已登记），只影响超过 20 轮的长会话；N 的最终取值由现场 eval 校准。
- 2026-09-17 阶段 0 续（D4 / D5，TDD）：checkpointer 改为 `aiomysql.create_pool`（`checkpoint_pool_minsize` / `maxsize` / `pool_recycle_seconds` 默认 1 / 10 / 1800，小于 MySQL `wait_timeout`）+ `AIOMySQLSaver(conn=pool, serde=白名单)`，`from_conn_string` 单连接形态退出生产；新增 `probe_checkpointer()`，`/ready` 的 mysql 探针在 saver 已接线时打 saver 自己的池；`/ready` 区分硬依赖（mysql / java_backend → 503）与软依赖（langfuse / llm → 200 + degraded）。真实 MySQL / TDSQL 上的连接池行为仍需现场验证。
- 2026-09-17 阶段 0 续 2（D4 / D5，TDD）：**请求级幂等** `app/api/idempotency.py`——以企微 `message_id` 对齐 `message_log.uk_message_id`：首次占位 → 跑图 → 回填 `reply_text`；重投已完成 → 回放上次回复（`outputs.replayed=true`）不重跑图；处理中 → 固定文案；无 message_id 不做幂等；存储故障只 warning（退化为无幂等）。`REQUEST_IDEMPOTENCY`（默认关，客户模板开）+ `message_log` 新增 `reply_text` 列（`sql/init.sql` 附 ALTER）。**LLM 指标 callback** `app/observability/llm_metrics.py`——`on_llm_end` / `on_llm_error` 自动 `emit_llm_call` / `emit_llm_tokens`（节点名取 `metadata["langgraph_node"]`），常驻于每次 graph 调用的 `config["callbacks"]`，`llm_failure_high` 告警与成本日报从此有数据。
- 2026-09-17 阶段 0 续 3（D5，TDD）：**LangFuse 注入路径统一**——删除 `app/graph/main.py` 图级 `_attach_langfuse_callbacks` 与 `app/main.py` 的 environment 分叉，`tracing._enabled()` 不再绑死 development，所有环境走 `routes.attach_request_trace` 请求级 handler（生产从此有 trace_id / session / user 契约与 trace_url）；入站 traceparent 信任改为独立开关 `TRUST_INBOUND_TRACEPARENT`（默认关）；`Langfuse(environment=)` 按环境切分；`scripts/langfuse/langfuse_eval.py` 自带 handler 并携带 `langfuse_session_id` / `trace_id` 与生产同契约。
- 2026-09-17 阶段 1 起步（D2 / D5，TDD）：`make_initial_state` 退役——一轮输入 → AgentState 的唯一入口收敛为 `app/api/turn_state.py::inputs_to_state`（从 routes 抽出），生产与 eval 同一路径；删除 M1 兼容层（它硬清空业务对象、写 6 个不存在的键）。lifespan 关闭段 `tracing.flush()`。
- 2026-09-17 阶段 1 · `expected_action` 提升顶层（D2，TDD）：新增 `ExpectedAction = Literal["place", "modify", "cancel", "inquiry", "close"]` 与 `AgentState.expected_action`（per-turn，ingest 重置，`SubgraphOutput` 放行）；`PlaceParams` / `CancelParams` 信封不再接受该键（`extra=forbid` fail-fast）；swap / option / close 全部写类节点改写顶层（option 两种撤单原来的 `request_cancel` / `cancel_request` 收敛为 `cancel`，意图仍由 `intent` 区分；提交 / 汇合节点不再逐节点转抄该键）；render 的期权询价无结果分支读顶层。**Java 契约结论**：`docs/api-contracts/java-backend.md` 明确后端只读 `answer` / `data.outputs.reply_text`，该键不在 Java 读取面；`_state_to_outputs` 新增顶层 `outputs.expected_action`，同时把它投影回 `outputs.place_params` / `outputs.cancel_params`（wire 兼容既有探针 / 日志读者，state 本身不改写），可在确认无外部读者后移除投影。
- 2026-09-17 阶段 1 · harness B 方言收敛（D6，TDD）：`harness/golden.py` 成为三方言唯一加载器——A（`categories/`）、B（`unified_golden.jsonl`：`conversation[{raw_content, quote_desc}]` + case 级 `expected`）、raw（`id + raw_content`），默认发现并入 B 文件，可执行样本 389 → 1310（多轮 9 → 260），混合方言 fail-fast。B 多轮的 case 级 expected 描述的是焦点轮（`swap/confirm` 是末轮、`option/place_from_quote` 是中间轮），故引入 `expected_scope="any_turn"` + `differ.check_case_assertions`（任一已执行轮同时命中即通过）；`quote_desc` 非空 → `quote_previous=True`，首轮标注引用只记录不回放。数据缺陷不掩盖：48 条某轮 `raw_content` 为空的 case 标 `skip_reason`，`select_runnable` 在 CLI / eval 显式报数后跳过；`check_fixture_consistency.py` 同时 lint 两份文件（一个文件一种方言、id 跨文件唯一），空轮与 9 条 `product_type=query` 以 WARNING 列出归 Issue #113。`scripts/ai_test_langgraph/` 标 deprecated。D6 其余项（业务拒绝单独桶、早停未执行轮记失败、`--backend dry-run` 真生效、`expected.place_params` 必填）待后续批次。
- 2026-09-17 阶段 1 · harness 判定口径收口（D6，TDD）：`_report_case` 出 `status ∈ {PASS, FAIL, REJECTED}`，后端业务拒绝且无其它 diff 的 case 进 REJECTED 桶，不再算 PASS，summary / markdown 分桶计数、`pass_rate` 只数 PASS；早停后未执行的轮次逐轮记 `runtime` 失败（多轮 case 不再因首轮拒绝静默通过）；`/health` 新增 `backend_mode`（`dry-run` / `real`），`_doctor` 据此对 `--backend` 把关——想 dry-run 却打在真后端、或想真回归却打在 dry-run 都拒绝启动，旧服务端不报模式时 dry-run 亦拒绝；`check_text_assertions(allow_dry_run=)` 让 dry-run 模式下 `DRY-RUN-` 标记不算失败。D6 仅剩写类 case `expected.place_params` 必填（需业务方抽检）。
- 2026-09-17 阶段 2 · RetryPolicy + 客户端单例 + 协议层解耦（D3，TDD）：`app/graph/retry.py`——`@io_node`（`@safe_node(retryable=IO_RETRYABLE)`：后端不可达 / LLM 限流超时 5xx 穿透，其余异常仍就地落 error）+ `add_io_node`（挂 `RetryPolicy(max_attempts=NODE_RETRY_MAX_ATTEMPTS)` + 节点级 `error_handler`，耗尽后 `retry_exhausted_handler` 写 ErrorInfo 与 `error:retry_exhausted` trace，cascade 照常）；每次穿透打 `otc_agent_node_total{status="retry"}`。**读写分界**：16 个只读 IO 节点（意图识别 / 抽取 / 选择 / 查询 / ticker 三路 LLM 与 GOATS）挂重试，下单 / 撤单 / 确认 / 平仓 / 询价 14 个写类节点保持 `@safe_node` 不重试——超时后重试可能重复下单，`tests/graph/test_retry_policy.py` 以清单守护；`add_io_node` 拒绝非 `@io_node` 函数（否则 safe_node 吞异常、RetryPolicy 静默失效）。`app/tools/http_pool.py`：lifespan 打开一个 `httpx.AsyncClient` 连接池（`trust_env=False`，limits 100/20），option / swap / ticker / GOATS agent 四个 Client 经 `acquire_http_client` 复用，超时逐请求按各自设置传入；测试 `transport=` 注入与未开池的脚本 / 探针走独占临时 client，既有 30 个 monkeypatch 边界不变。`app/tools/bot_context.py`：`BotContext.from_state` / `missing_required` / `to_wire` 取代三份重复的 `_context` / `_message_id`，协议层只吃上下文模型；`call_*_backend(state, ...)` 签名不变，边界处转换。未做：`@safe_node` 的 `(state, config)` / `Runtime` 注入（当前无节点需要）。
- 2026-09-17 阶段 2 · `extract_inquiry` 拆子图 + `last_confirmed_params`（D3 / D4，TDD）：期权询价三条管线（快速询价 GOATS 直传 / 代码型标的预检 / LLM 抽取）做成图边——`inquiry_fast_parse` → `inquiry_fast_submit`、`inquiry_precheck` → `inquiry_reject`、`inquiry_extract` → `inquiry_resolve` → `inquiry_submit`，四个只读阶段 `@io_node` 挂 RetryPolicy，两个提交阶段不重试；私有 `InquiryState`（`iq_*`）+ `InquiryOutput`；LLM 失败归因到 `inquiry_extract`（此前整节点一个名）；汇总条目沿用 `option_extract_inquiry` 名与 decision 口径，测试 monkeypatch 边界不变，option 图原生嵌入。ConversationMemory：`AgentState.last_confirmed_params`（跨轮持久化，ingest 不重置，不在 SubgraphOutput）由主图新节点 `remember_confirmed_params`（render 之后、record_history 之前）写入——本轮无 error、`api_code == 0`、`expected_action ∈ {place, modify, inquiry, close}` 且从业务对象 / 后端回复（按产品线 `H-` / `Q-` / `CO-` 正则）拿到订单号时覆盖，撤单 / 确认回合不改写；读取点 `app/graph/memory.py::memory_order_ids(state, product_type)`：swap 三确认、option 确认下单 / 确认撤单、close 确认平仓 / 确认撤销在**文本抽不到单号**时回退到记忆。**优先级决定**：显式单号 > 引用消息 > 记忆——记忆只补裸确认，不扩大操作范围（close 点名序号 / 合约但对不上仍回请求补充）。
- 2026-09-17 阶段 2 · 节点延迟直方图 + 结构化日志（D5，TDD）：`otc_agent_node_latency_ms{node}` 独立直方图，`emit_node_completed` 不再往 intent 直方图写 `product_type=unknown` + `node` label 的寄生样本，`alerts.py` P95 解析器删除 `node=` 字符串过滤 hack；`@safe_node` 单一计时——节点自写的本节点 TraceEntry 缺 `elapsed_ms` 时补上（`node_trace.duration_ms` 不再恒 NULL），已有值与其它节点条目不动。`app/observability/logs.py`：structlog 接管 stdlib logging（业务代码不改写），`LOG_FORMAT=auto|json|console`（auto = development 控制台、其余 JSON），`LOG_LEVEL` 终于被消费；`bound_request_context` 在 routes 里包住整次图调用，`trace_id` / `conversation_id` / `message_id` 经 contextvars 进每条日志，退出时只解绑自己绑的键；lifespan 起点 `configure_logging_from_settings`（幂等，不动 uvicorn 自己的 handler）。
- 2026-09-17 阶段 3 · Dify 残留 B / C 级清理（D1）：**C 级删除**——打 tag `dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建）` 后移除 dify/（sync.py + README + 1.7MB YAML）、scripts/export_dify_prompts.py、sync-dify-prompts / migrate-prompt 技能、dify-reviewer / prompt-migrator agent 及 `.agents` 镜像、mock_api rerank 桩、tests/api/test_20_dify_rerank.py（连同 ~~`tests/api/_utils.py`~~ 里的明文 Dify key）、3 个零流量 *_v2.md、docs/archive/dify-originals/（1.1MB）；日期型对比报告移入 `docs/archive/reports/`。**B 级**——19 份业务 `.md` 删除零消费的 node_id / model 元数据行；12 份只作 Dify 输入形态参照的死 `[user]` 段删除（现役 `[user]` 只剩 `swap/place_order.md`、`swap/fresh_counterparty.md`）；system 占位符改原生名 `{{counterparty_list}}` / `{{current_date}}`，`fresh_counterparty` 不再用 Dify 原文当 `render_user` 键；`app/main.py` description 与加载器 / 规则 / 根文档口径同步。**未做**：`scripts/shadow_compare.py` 是 M4 灰度工具链的一部分（CLAUDE.md 列为就绪能力），是否退役待 F4.1 决策；ADR 0022 保留原位（已标废弃，移动会打断 ADR 互引）；一级路由中文标签改原生 Literal 会改 LLM 输出词汇表，需 eval 门；~110 处"与 Dify 对齐"注释与 ~30 处测试口径未逐条改写。

## 附录 · Dify 残留分级清单（摘要）

以下工作量与分类为原方案快照；原生 endpoint / adapter 迁移按 D7 暂缓，shadow 工具保留。

- **A 保留**：`app/api/routes.py` wire schema + 502 语义 + `_INPUT_FIELD_ALIASES`；`app/tools/{swap,option}_client.py` 意图枚举；`app/tools/goats_rfq.py` 签名；`docs/on-call-runbook.md` 回切预案（G5.2b 后失效）。
- **B 替换**（19-26 人日）：原生 endpoint + adapter；`DifyWorkflowRun*` 重命名；提示词 `node_id` / `model` 行；31 处死 `[user]` 段与占位符；`fresh_counterparty.py:24-28` hack；4 处 system 占位符命名；`intent_route.py:36-51` 中文标签；两条纪律；~110 处注释；~30 处测试；`option_close`/`close`；`app/main.py:68` description；活跃文档。
- **C 删除**（4-6 人日）：dify/、scripts/export_dify_prompts.py、sync-dify-prompts / migrate-prompt 技能与 dify-reviewer / prompt-migrator agent（含 `.agents` 镜像）、`mock_api` rerank 桩、tests/api/test_20_dify_rerank.py、3 个 0 流量 *_v2.md、docs/archive/dify-originals/、日期型对比报告、ADR 0022 移 archive。（2026-09-17 除 shadow_compare 与 ADR 0022 外已全部执行，见落地记录）
- **安全（历史提案）**：曾提出对 ~~`tests/api/_utils.py:12`~~ 中的历史凭据执行 revoke；本轮历史 GOATS 测试凭据按 #218 用户裁决不处理。

## 关联

- 评估报告：`docs/langgraph-architecture-assessment.md`
- ADR 0000 / 0001 D3 D6 / 0009 / 0014 / 0021 / 0023（见文首修订关系）

## 2026-09-22 巡检裁决与本地实现

- #218：用户决定不处理历史 GOATS 测试凭据，不纳入本轮验收。
- #219：Python 依赖已限制 PyMySQL < 1.2；已部署环境与离线包核查仍待执行，不宣称现场已修复。
- #223：7dfed2a 在原 IO 节点最后一次失败时返回错误，恢复正常图边与并行收尾；专项 RED 8 条失败，GREEN 85 条通过。
- #224：6938513 建立共享节点契约目录并保留应用/评测各自范围，修复 render.api_code 输入遗漏；专项验证结果见本轮交付记录。上述提交仅在本地，待合入。
- shadow_compare、测试与 shadow-test 技能继续保留，从当前删除范围中移出；去留待 F4.1 灰度与回滚安排确定。
- 全量 pytest、真实业务回归、性能测试留待统一验收；Java 保持零修改。
