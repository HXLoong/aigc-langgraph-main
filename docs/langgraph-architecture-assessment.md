# LangGraph 架构专题评估：现有实现对 LangGraph 特性的落实程度与彻底重构路线

- 日期：2026-09-17
- 基线：`main` @ `280eab6`（langgraph 1.2.11 / langgraph-checkpoint 4.2.0 / langgraph-checkpoint-mysql 3.0.0 / langfuse 4.15.2）
- 目的：回答"现在的代码是不是按 LangGraph 范式开发的"，并给出**彻底摆脱 Dify 形态、按 LangGraph 原生架构重构**的目标模型与分阶段路线。决策见 [ADR 0024](./adr/0024-langgraph-native-rearchitecture.md)。
- 方法：5 路并行只读评审（图与共享 State / Checkpointer 与多轮 / 可观测 / 黄金数据集与评估台 / Dify 残留），每条结论附 `file:line`，关键结论由主评审复核。

## 一、执行摘要

**总评：外形是 LangGraph，内核仍是 Dify。** 图拓扑、`@safe_node`、reducer、checkpointer 接线、cascade 防御这些"骨架"做对了，但四个决定性的 LangGraph 能力没有被真正使用，而它们恰好是金融场景最需要的：

| 维度 | 评分（5 分制） | 一句话结论 |
|---|---|---|
| 图拓扑与共享 State | **2.5** | 节点纯函数、路由纯函数、reducer 克制；但子图靠手写 `ainvoke` + `Overwrite` 包装而非原生嵌入，1.x 特性（Command / Send / RetryPolicy / CachePolicy / durability / input-output schema）零使用，ticker 12 步管线是"Python 写的图"，`render` / `place_close` / `extract_inquiry` 是 Dify code 节点原样搬来的厚节点 |
| Checkpointer 与多轮 | **2.0** | 接线、单例、fail-fast、thread_id 契约正确；但除 `history_messages` 外 checkpoint **只写不读**，业务对象既不被消费也不被清理成为渲染污染源；生产 saver 是**单连接无重连**、无请求级幂等（重试即重复下单）、serde 未固化、`history_messages` 无界增长 |
| 可观测（LangFuse / metrics / 日志） | **1.5** | 生产走裸 `CallbackHandler`，`tracing.py` 的 trace_id 契约在生产是死码；LangFuse 无 session / user / tags；LLM 指标零调用导致 P1 告警永不触发；敏感字段明文出境；LangFuse 探针可拖垮 `/ready` |
| 黄金数据集与评估台 | **1.5** | 素材 2700+ 条、多轮语义建模到位；但 CI 自 2026-05-12 不跑、主力 921 条数据集被主力加载器判为非法、Judge 无 ground truth、仅有的 6 条节点级期望因 `wind_code`/`windCode` 别名 bug 恒假失败、写类链路 `place_params` 零端到端期望 |
| Dify 残留 | **2.0** | 956 处 "Dify"；唯一业务入口是 Dify Workflow Run 形态；`route_rules.py:8`"改业务逻辑必须先改 Dify 源再同步"与 git-workflow"冲突永远选 Dify 原始版本"仍是现行纪律；提示词 24 行 `model` 元数据与 ADR 0020 矛盾 |

**对"彻底重构"的核心判断**：在评估台通电（CI + 数据契约）之前，任何重构都无法用现有资产证明行为等价；因此路线图第 0 阶段不是改图，而是**让守护重新通电 + 修掉三条 P0 生产风险**（单连接 saver、无幂等、敏感字段出境）。之后按"State 契约 → 子图原生化 → 协议原生化 → Dify 资产退役"四段推进。

## 二、图拓扑与共享 State

### 2.1 事实

- `AgentState`（`app/graph/state.py:111-186`）38 条声明 / 37 个唯一字段，`reply_text` 重复声明（:177 与 :184）；仅 `history_messages`（:155）与 `trace`（:180）有 `add` reducer，其余 35 个单值覆盖；21 个是入口 / 管道扁平字段，业务对象只有 6 个。
- 主图（`app/graph/main.py:118-162`）14 节点 2 条 conditional；三个子图用 `_as_subgraph_node`（:77-90）手写 `await graph.ainvoke(state, config)` 再把 `trace` / `history_messages` 用 `Overwrite` 回填——不是 `add_node(name, compiled_subgraph)` 原生嵌入。三子图共享同一 `AgentState`，`input_schema` / `output_schema` / `context_schema` 全仓零命中。
- LangGraph 1.x 特性使用：仅 `Overwrite`。`Command` / `Send` / `interrupt` / `RetryPolicy` / `CachePolicy` / `durability=` / `@task` / `astream` 全部为零。`interrupt` 不用有 ADR 0021 背书。
- `@safe_node`（`app/graph/safe_node.py:23`）签名锁死单参数，节点拿不到 `RunnableConfig` / `Runtime`，依赖注入只能靠闭包工厂穿透 `build_main_graph`；无重试，LLM / HTTP 瞬时抖动直接变永久 `error` → fallback 兜底话术。`record_history`（`app/nodes/record_history.py:9`）是唯一无 `@safe_node` 的节点。
- 节点内直接调后端并每次新建客户端：option 7 处、close 7 处、swap 4 处、`multimodal.py:51` 直开 `httpx.AsyncClient`；协议层直接吃 `AgentState`（`swap/backend.py:41-58,122`）。
- "用 if/else 写图"：`render.py:124-259` 18 个 return 分支零 trace；`close/place_close.py:123-337` 215 行单节点 6 阶段；`option/extract_inquiry.py:71-183` 三管线合一；`swap/confirm.py:48-60/:105-110` intent→action→intent 绕圈。
- "本该 Send 并行 / 子图隔离"：ticker resolver（`app/subgraphs/ticker/resolver.py:5-13,201`）12 步 DAG 用 `asyncio.gather` 手写，目录无 `graph.py`，对 trace / checkpoint / retry / LangFuse 全透明；swap `select_counterparty → select_ticker` 被迫串行（根因 `place_params` 无 reducer）；子图可改写父图路由键 `intent`（`multimodal.py:143`、`close/place_close.py:166,329`）。
- 一轮的边界分散三处维护：`routes.py:275-282` setdefault 清当轮输入、`main.py:93-95` `_reset_turn_trace` 清 trace、`ingest.py:41-47` 清输出。
- `app/state.py:15-44` `make_initial_state` 是活着的 M1 兼容层：硬清空 5 个业务对象、写 6 个不存在的键，仍被 `scripts/langfuse/langfuse_eval.py:86` 使用——**eval 与生产走不同的初始化路径**。

### 2.2 做对了什么

节点与路由都是纯函数；reducer 只用在真正需要累加的字段；`@safe_node` + `has_error` 的 cascade 体系自洽且三图一致；`TRACE_TEXT_LIMIT` 截断显示团队有 checkpoint 体积意识；`business_params.py` 的 `validated_*` 给 dict 业务对象加了形状权威；checkpointer 生产 fail-fast；不用 interrupt 是显式决策而非遗漏。

### 2.3 与 LangGraph 范式的差距

| 差距 | 后果 |
|---|---|
| 子图不是子图 | 丢掉子图命名空间流式、子图内节点级 checkpoint、子图内 interrupt 可恢复、父图对子图设 Retry / Cache；`Overwrite` 那段是手工补丁 |
| 无 input / output schema | 37 个字段对所有子图全裸暴露，子图改写父图 `intent` 这类 bug 无类型保护 |
| 无 RetryPolicy | 网络抖动 = 业务失败 = 兜底话术 |
| 无 Send | 并行只能手写 `asyncio.gather`，图外之图不可观测 |
| 无 durability 决策 | 写路径（下单 / 平仓 / 确认）提交前 state 是否落盘无人决策，与"重复下单"直接相关 |
| `expected_action` 藏在 dict 里 | 12+ 处读写维持一个隐式状态机（注意：它是 Java operate 契约 + ADR 0001 D5 节点合并的产物，**不是 Dify 残留**，清理时不可误删） |

## 三、Checkpointer 与多轮

### 3.1 事实

- `app/checkpointer/factory.py:36` `AIOMySQLSaver.from_conn_string(uri)`：社区包该入口只 `yield` **一条** `aiomysql` 连接（`langgraph/checkpoint/mysql/aio.py:41-62`），saver 用一把 `asyncio.Lock` 串行化全部 checkpoint IO；无重连；`/ready` 的 mysql 探针另开新连接（`health_probes.py:44-72`），saver 连接被 `wait_timeout` 杀掉后 `/ready` 仍返回 ok。`from_conn_string` 未传 `serde=`，走 4.2.0 的 permissive 默认（官方注明未来将 block），只有 `tests/test_api_turn_inputs.py:73-75` 配了白名单。
- `routes.py:208-214` config 只有 `thread_id` / `metadata.trace_id` / `recursion_limit`；`durability` 未设 → 默认 `"async"` 每个 superstep 落盘；`_as_subgraph_node` 透传父 config，子图写到 `checkpoint_ns="swap:<task_id>"` 且永不恢复，纯写放大。
- 跨轮真正被读的只有 `history_messages`；`tickers` / `place_params` / `cancel_params` / `confirm` 物理保留但无业务节点当"上一轮结果"读；二阶段确认从 `raw_text` / `quote_content` 正则重抽单号（`swap/confirm.py:99-104`、`close/confirm_close.py:36-39`）。
- `ingest` 只清 `reply_text/api_result/api_code/error`（`ingest.py:56-62`），`render.py:247/:249` 无 intent 守卫地读残留 `close_params` / `cancel_params`（`:234` 只补了 confirm 分支的守卫）。
- 无请求级幂等：`message_id` / `guid` 不去重；`sql/schema.sql:8-31` 的 `message_log`（含 `uk_message_id`）**定义了但全仓无写入方**；`node_trace` 无幂等键（`persist.py:42-44` 自认）；无 alembic。
- `history_messages` `Annotated[list, add]` 无上限无窗口（`state.py:155`），提示词侧 `blocks.format_history` 全量渲染；企微群 thread 长期存在 → token / 延迟 / context 超限 + `checkpoint_blobs` O(n²)。
- Store 零使用；`get_state_history` 零使用；CI 无 MySQL service，`AIOMySQLSaver` 路径零覆盖（ADR 0009:46 自认）。

### 3.2 金融场景风险排序

| 级别 | 风险 | 修法 |
|---|---|---|
| P0 | 单连接 saver 无池、无重连、探针探不到 → 全站失忆 / 雪崩 | `AIOMySQLSaver(conn=await aiomysql.create_pool(..., autocommit=True, pool_recycle<wait_timeout))`（社区包 `_ainternal.py:74-83` 已支持）；`/ready` 改为打 saver 自身 |
| P0 | 无请求级幂等：Java 重试 / 企微重投 / 运维重放 → 重复下单 / 重复平仓 | 路由层以 `(conversation_id, message_id)` 去重，启用已定义的 `message_log`，冲突即回放上次 `reply_text` |
| P1 | 状态串线：残留业务对象被渲染成"已收到撤单请求" | per-turn 业务对象重置 + `render` intent 守卫 |
| P1 | `history_messages` 无界 | 自定义 reducer 保留最近 N 轮（或 token 预算） |
| P1 | 生产 serde 未固化；`history_texts` 只认 Message 形态（`option/place_params.py:247-249`）dict 形态静默丢弃 | `from_conn_string(uri, serde=JsonPlusSerializer(allowed_msgpack_modules=...))` + 双形态兼容 |
| P2 | durability 默认 `async` 写放大 | 图内无 interrupt，`durability="exit"` 零语义损失 |

## 四、可观测性

### 4.1 事实

- 四个互不知情的 CallbackHandler 入口：`tracing.py:138-141`（请求级，**仅 development**）、`graph/main.py:172-196`（图级裸 `CallbackHandler()`，生产）、`harness/langfuse_client.py:47-55`（零调用死代码）、`scripts/ai_test_langgraph/...:507-526`。`app/main.py:55` 与 `tracing.py:68-76` 环境互斥 → **生产环境里 trace_id 契约、traceparent、trace_url 全是死码**。
- `_build_run_config` metadata 只有 `{"trace_id"}`；`langfuse_session_id` / `langfuse_user_id` / `langfuse_tags` 零命中；`conversation_id` / `message_id` 从未传给 LangFuse → 多轮在 LangFuse 里是 N 条互不关联的 trace，`docs/observability.md:285`"按 conversation_id 查 trace"不可用。
- `tracing.py` 客户端注册顺序倒置（`:138` 构造 handler 早于 `:150` `_ensure_client()`，traceparent 分支 `:146-148` 提前 return）→ 首次请求与全部 traceparent 请求 handler 为 no-op。
- `emit_llm_call` / `emit_llm_tokens`（`metrics.py:288-290,353-377`）**零调用** → `llm_failure_high`（P1，ADR 0019）永不触发，`llm_cost_report` 恒空；`docs/observability.md:193` 却标"✅ 完整实现"。节点延迟寄生在 `otc_agent_intent_latency_ms` 上（`metrics.py:252-256`），告警侧靠字符串过滤补救（`alerts.py:382-389`）。
- `health_probes.py:75-93` 探 LangFuse，任一 fail → `/ready` 503：可选观测依赖挂掉会把业务 Pod 摘出负载均衡。
- `TraceEntry.llm_output` 明文写入对手名 / 数量 / 价格（`swap/place_order.py:162-168`、`fresh_counterparty.py:73-79`、`close/place_close.py:171,270,306,334`）→ `node_trace.output_preview`；LangFuse client 两处均未传 `mask=`；默认 host 是 `cloud.langfuse.com`。
- `structlog` 声明依赖但零 import，无日志配置，`settings.log_level` 未消费，日志无 trace_id；业务进程无 `flush`；LLM SDK 层 `max_retries=2` 不产 callback / span / metric。
- `astream` / `astream_events` 零使用（上游 Java 写死 blocking，暂不建议改）。

### 4.2 与范式的差距

LangGraph + LangFuse 的原生契约是"一个 thread = 一个 session，每次 invoke = 一个 trace，`config.metadata` 携带 session / user / tags，callback 自动嵌套 span"。现状是把 `trace` 手写进 state 又落 MySQL（这条双轨对金融审计是对的，应保留），但 LangFuse 这条轨在生产上既没有会话维度也没有关联键，等于只有一半。

## 五、黄金数据集与评估台

### 5.1 事实

- `tests/fixtures/categories/` 389 条（A 方言 `send_text` / `sub_scenes` / `response_contains`，互换 376 : 期权 13，多轮 9 条，`expected.output` 0 条，多模态 0 条）；`unified_golden.jsonl` 921 条（B 方言 `conversation[]` / `expected.output`，多轮 251 条）**被 `harness/golden.py:84-87` 判为 legacy 直接抛 `ValueError`**，`tests/fixtures/README.md:59` 的官方命令实测即报错；`old_typing/` 1412 条归档。
- `harness/differ.py:81` 读 `wind_code`，而 HTTP outputs 经 `wire_model` `by_alias=True` 输出 `windCode` → 全仓仅有的 6 条节点级 ticker 期望在 `python -m harness run` 下 100% 恒假失败；`tests/test_harness.py:88-112` 固化了错误契约。
- `scripts/langfuse/langfuse_eval.py` 在 categories 上 `expected_output` 为空（0/389）→ Judge 无 ground truth，叠加 `option_judge.md` 的宽松原则（业务拒绝 = 1.0，主参数任一对 = 1.0）与 0.7 阈值，评分近乎必然虚高；`upload_golden_to_langfuse.py` 有 `build_expected` 兜底而本地没有 → 本地 / 云端口径不一致。
- 三套评估台并行：`harness/`（HTTP + 确定性断言）、`scripts/ai_test_langgraph/`（4389 行，支持三方言）、`scripts/langfuse/langfuse_eval.py`（进程内 + Judge），加载器 / 断言集 / 报告格式各不相同。
- `harness/cli.py:47-49` 后端业务拒绝算 PASS，`:29` `zip(strict=False)` 早停后轮次静默跳过 → 系统性假绿；`--backend dry-run` / `--checkpoint` 开关不生效（`:148-149` / `:109-117`）。
- `.github/workflows/ci.yml:4-6` 自 2026-05-12 只剩 `workflow_dispatch`：push / PR 上 1976 个 pytest 用例、fixture lint、ADR lint 一条都不跑；eval 从未进 CI。
- D 桶（生产真实流量 → golden）通路不存在，`harness sync-golden` 子命令不存在（ADR 0002 宣称已就绪）；C 桶 LLM paraphrase 实际只有 2 条。

### 5.2 对重构的含义

写类链路的 `place_params`（真正有资金后果的对象）在端到端集里零期望，只在 6 条 mock-LLM 单测里有；也就是说重构后 `orderList` 某个字段悄悄少填，389 条端到端可能全绿。而多轮（checkpointer 最容易在重构中被破坏的部分）在现役集上只有 2.3%。**守护力最弱的地方正好是风险最高的地方。**

## 六、Dify 残留分级

全仓 197 文件 / 956 处 "Dify"。分级（详细文件清单与人日估算见 ADR 0024 附录）：

- **A 级 · 必须保留**（外部契约，0 人日）：`routes.py` wire schema 与 502 语义、`_INPUT_FIELD_ALIASES`（本质是 Java Worker 透传契约）、swap / option client 的意图枚举（Java `SwapIntentionType`）、GOATS 签名、on-call 回切预案（G5.2b 后失效降为 C）。**`expected_action` / `place_params` / `confirm_modify_order` 不是 Dify 残留。**
- **B 级 · 可替换为 LangGraph 原生**（19-26 人日）：原生 endpoint `POST /v1/runs` + Dify 形态降为 adapter（ADR 0001 D3:47 已授权"另开 ADR"）；`DifyWorkflowRun*` 重命名；删 24 行 `node_id` + 24 行 `model` 元数据（`model` 行与 ADR 0020 矛盾）；31 处死 `[user]` 段与 Dify 占位符迁入 `PromptSpec.user_builder`；`fresh_counterparty.py:24-28` 用 Dify 原文当变量名的 hack；4 处 system 占位符改原生名；一级路由中文标签 `_LABEL_MAP`（`intent_route.py:36-51`）改原生枚举；**解除 `route_rules.py:8`"改业务逻辑必须先改 Dify 源"与 `git-workflow.md:109-110`"冲突永远选 Dify 原始版本"两条纪律（0.5 人日，决策价值最高）**；~110 处"与 Dify 对齐"注释改业务语义；~30 处测试去 Dify 参照；`option_close` / `close` 命名对称化；活跃文档口径重写。
- **C 级 · 可直接删除**（4-6 人日，-1700 行 -2.8 MB）：`dify/sync.py` + `dify/yaml/`、`scripts/export_dify_prompts.py`、`scripts/shadow_compare.py` 及指南、三个 Dify 技能与两个 Dify agent（含 `.agents` 镜像）、`mock_api` rerank 死桩、`tests/api/test_20_dify_rerank.py`、3 个 0 流量 `*_v2.md`、`docs/archive/dify-originals/`、日期型对比报告、ADR 0022 移 archive。
- **独立安全动作**：`tests/api/_utils.py:12` 已入 git 的明文 Dify API key 需 revoke 并改环境变量读取。

## 七、目标架构（LangGraph 原生）

详见 ADR 0024。要点：

1. **State 分层**：`AgentState` 拆为 `TurnInput`（每轮由 API 注入、不持久化语义）/ `ConversationMemory`（`history_messages` 窗口 reducer + 上一轮已确认业务对象）/ `BusinessObjects`（Pydantic，`expected_action` 提升为顶层 `Literal`）/ `Engineering`（`trace` per-turn、`error`）；子图声明 `input_schema` / `output_schema`，父图路由键对子图只读。
2. **子图原生化**：`add_node("swap", build_swap_graph())` 原生嵌入，删 `_as_subgraph_node` 与 `_reset_turn_trace`；ticker resolver 变真子图（私有 state + `Send` 按关键词 fan-out + merge）；swap 选对手 ‖ 选标的并行（`place_params` 按 order_index 合并 reducer 或拆两个通道 + join）；`place_close` / `render` / `extract_inquiry` 拆成小节点或表驱动。
3. **节点契约**：`@safe_node` 支持 `(state, config)` / `Runtime` 注入；IO 节点让可重试异常穿透到 `RetryPolicy`，重试耗尽才落 `error`；HTTP 客户端 lifespan 单例；协议层吃 `BotContext` 而非 `AgentState`。
4. **持久化契约**：saver 连接池 + serde 白名单 + `durability="exit"`（无 interrupt 时）；写路径提交前的 durability 显式裁决；请求级幂等（`message_log`）；`history_messages` 窗口；确认链路优先读上一轮 `place_params` 而非重抽文本；Store 留给跨 thread 偏好（可选）。
5. **可观测契约**：单一请求级注入，`metadata` 携带 `langfuse_session_id=conversation_id` / `langfuse_user_id` / `langfuse_tags` / `environment`；LLM 指标接 callback（复用 `harness/token_tracker.py` 解析）；独立节点延迟直方图；`mask=` + `TraceEntry` 脱敏；`/ready` 软硬依赖分离；structlog + trace_id contextvar。
6. **评估契约**：CI 通电（fast job < 2 min）；`harness` 成为唯一 gate（合并三方言加载器，B 方言 921 条并入，`windCode` 修正，假绿修正，`dry-run` 真生效），`langfuse_eval` 降为 Judge + 上报薄层；写类 case 补 `expected.place_params`；每个线上 P0/P1 先补 fixture 再修代码；D 桶反向脚本。
7. **协议原生化**：`POST /v1/runs` 类型化请求 / 响应 + 结构化 trace；Dify 形态降为独立 wire 兼容 adapter，仅为回滚期服务，G5.2b 后删除。

## 八、分阶段重构路线

| 阶段 | 目标 | 内容 | 门槛 |
|---|---|---|---|
| **0 · 通电与止血**（1-2 周） | 让守护可用、消除 P0 生产风险 | CI 恢复 push/PR fast job；`windCode` bug；saver 连接池 + serde 白名单 + `/ready` 打 saver；请求级幂等；`durability="exit"`；LangFuse session/user 维度 + 注入路径统一；LLM 指标接 callback；`/ready` 软硬分离；`record_history` 加 safe_node；解除两条"Dify 为真源"纪律；revoke 明文 key | 全量 pytest GREEN；`harness run` 6 条 winners 期望真实通过；CI 在 PR 上跑 |
| **1 · State 契约**（2-3 周） | 让重构可被证明等价 | B 方言并入 harness（可执行样本 389 → 1310，多轮 9 → 260）；写类 case 补 `expected.place_params`（可从 `response_contains` 反向生成）；Judge ground truth 兜底 + 阈值 0.9 + 中间档；`AgentState` 分层 + 子图 output schema；`history_messages` 窗口 reducer；per-turn 业务对象重置 + render 守卫；`make_initial_state` 退役；`expected_action` 提升顶层 | eval PASS ≥ 阶段 0 基线；多轮回归集 GREEN；子图不能再改写父图 `intent`（类型级） |
| **2 · 子图原生化**（3-4 周） | 图即架构 | 原生子图嵌入；ticker 真子图 + Send；swap 选对手 ‖ 选标的；`place_close` / `render` / `extract_inquiry` 拆节点；RetryPolicy / CachePolicy；客户端单例；协议层解耦；`@safe_node` 支持 Runtime | trace 每步可归因；节点级延迟直方图有数据；eval PASS ≥ 阶段 1 |
| **3 · 协议原生化 + Dify 退役**（2-3 周） | 彻底摆脱 Dify 形态 | `POST /v1/runs`；Dify adapter；`DifyWorkflowRun*` 重命名；提示词元数据 / 死 `[user]` 段 / 占位符 / 中文路由标签清理；~110 处注释与 ~30 处测试口径改写；C 级资产删除；文档重写；Java 侧 `agentUrl` 切换 | Java 联调通过；回切预案改为"回滚上一版本 LangGraph"而非回 Dify |
| **4 · 持续**（并行） | 数据闭环 | D 桶反向脚本；覆盖矩阵配额；多模态样本；Store 跨 thread 记忆（按业务诉求） | 每个线上事故先补 fixture |

## 九、本次已落地（阶段 0 首批，TDD，均无需真 LLM 即可验证）

| 改动 | 文件 | 对应发现 |
|---|---|---|
| `winners` 断言按 `windCode` 比对 + 真实 `TickerCandidate` 契约测试 | `harness/differ.py`、`tests/test_harness.py` | 第五节 R4 |
| `record_history` 纳入 `@safe_node` | `app/nodes/record_history.py` | 第二节 |
| `AgentState.reply_text` 重复声明清理；`api_result` 类型改为 `str \| dict \| list \| None`；AST 级重复字段守护测试 | `app/graph/state.py`、`tests/graph/test_state_schema.py` | 第二节 |
| `config.metadata` 增加 `langfuse_session_id` / `langfuse_user_id` / `langfuse_tags` | `app/api/routes.py` | 第四节 P0-2 |
| `graph.ainvoke(..., durability="exit")` | `app/api/routes.py` | 第三节 R6 |
| 生产 saver `serde` 白名单固化（`CHECKPOINT_ALLOWED_MODELS`） | `app/checkpointer/factory.py` | 第三节 R5 |
| `tracing.py` 先注册 client 再构造 handler（含父 Trace 分支） | `app/observability/tracing.py` | 第四节 P1-1 |
| 撤销"改业务逻辑必须先改 Dify 源"与"冲突永远选 Dify 原始版本" | `app/nodes/route_rules.py`、`.claude/rules/git-workflow.md` | 第六节 B8 / C12 |

| **重构 1 · 子图原生嵌入**：`merge_by_id` reducer（`TraceEntry` / `Message` 带不参与 dump 的 id）；`SubgraphOutput` output_schema；`add_node(name, compiled)` 替代 `_as_subgraph_node` | `app/graph/state.py`、`app/graph/main.py`、三个 `graph.py`、`tests/graph/test_reducers.py`、`tests/graph/test_subgraph_contract.py` | 第二节 2.3 前两行 |
| **重构 2 · ticker 真子图**：私有 State + 三路 LLM 并行分支 + `Send` 按 orgStr 并行 GOATS/rank + 按序汇总；`checkpointer=False`；façade 不变 | `app/subgraphs/ticker/graph.py`、`resolver.py`、`tests/subgraphs/ticker/test_graph.py` | 第二节 2.1（本该 Send 并行）|
| **重构 3 · swap 选对手 ‖ 选标的 并行**：指针通道 + `swap_apply_picks` 汇合节点，`place_params` 语义不变 | `app/subgraphs/swap/{select_counterparty,select_ticker,apply_picks,graph}.py`、`app/graph/state.py`、`tests/subgraphs/swap/test_select_chain.py`、`test_graph_routing.py` | 第二节 2.1（被迫串行）|
| **重构 4 · render 分支可观测**：`_render_branch` 返回 `(update, decision)`，每个出口一条带 decision 的 TraceEntry | `app/nodes/render.py`、`tests/nodes/test_render_decision.py` | 第二节 2.1（if/else 代替图边，零 trace）|
| **重构 5 · place_close 拆子图**：7 阶段节点 + 私有 State + output_schema，早退做成图边，错误归因到阶段 | `app/subgraphs/close/place_close.py`、`close/graph.py`、`tests/subgraphs/close/test_place_close_graph.py` | 第二节 2.1（215 行单节点 6 阶段）|
| **重构 6 · 业务对象 per-turn + 一轮边界收敛到 ingest**：ingest 清空业务对象 / 指针通道 / trace（Overwrite），删 `_reset_turn_trace`；`@safe_node` Overwrite 感知 | `app/nodes/ingest.py`、`app/graph/safe_node.py`、`app/graph/main.py`、`tests/nodes/test_ingest_reset.py`、`tests/graph/test_safe_node_overwrite.py` | 第三节 R3（状态串线）、第二节（一轮边界分散三处）|
| **重构 7 · history_messages 窗口**：`merge_history` reducer（按 id 合并 + 最近 N 条），`HISTORY_WINDOW_MESSAGES` 默认 40 | `app/graph/state.py`、`app/config.py`、`.env.customer.template`、`tests/graph/test_reducers.py` | 第三节 R4（无界增长）|
| **阶段 0 续 · saver 连接池 + 探针自愈 + /ready 软硬分离**：`aiomysql.create_pool` + `pool_recycle`，`probe_checkpointer()`，硬依赖才 503 | `app/checkpointer/factory.py`、`app/config.py`、`app/observability/health_probes.py`、`app/api/health.py`、`tests/test_checkpointer_wiring.py`、`tests/observability/` | 第三节 R1、第四节 P0-5 |
| **阶段 0 续 2 · 请求级幂等 + LLM 指标 callback**：`message_log` 去重回放（`REQUEST_IDEMPOTENCY`）；`LLMMetricsCallback` 常驻 config.callbacks | `app/api/idempotency.py`、`app/api/routes.py`、`app/main.py`、`app/observability/llm_metrics.py`、`sql/schema.sql`、`tests/test_api_idempotency.py`、`tests/observability/test_llm_metrics_callback.py` | 第三节 R2、第四节 P0-3 |
| **阶段 0 续 3 · LangFuse 注入统一**：删图级注入与 environment 分叉，请求级 handler 全环境生效，traceparent 信任独立开关，eval 同契约 | `app/observability/tracing.py`、`app/graph/main.py`、`app/main.py`、`app/config.py`、`scripts/langfuse/langfuse_eval.py`、`tests/test_api.py`、`tests/test_langfuse_eval_pipeline.py` | 第四节 P0-1 / P0-2 |
| **阶段 1 起步 · 入口唯一化 + flush**：`inputs_to_state` 为生产 / eval 共用入口，删 M1 兼容层；退出前 flush LangFuse | `app/api/turn_state.py`、`app/api/routes.py`、`scripts/langfuse/langfuse_eval.py`、`app/observability/tracing.py`、`app/main.py`、`tests/test_multiturn_state.py` | 第二节（eval 与生产初始化路径不同）、第四节 P1-5 |
| **阶段 1 · `expected_action` 提升顶层**：`ExpectedAction` Literal + `AgentState.expected_action`（per-turn，SubgraphOutput 放行）；信封去键 fail-fast；13 个写类节点写顶层，render 读顶层；outputs 顶层暴露 + 投影回信封做 wire 兼容 | `app/graph/state.py`、`app/graph/business_params.py`、`app/nodes/{ingest,render}.py`、`app/api/routes.py`、swap / option / close 写类节点、`tests/graph/test_state_schema.py`、`tests/test_state_to_outputs.py` | 第二节（`expected_action` 藏在 dict 里，12+ 处读写维持隐式状态机）|
| **阶段 1 · harness B 方言收敛**：`harness/golden.py` 三方言唯一加载器，默认发现并入 `unified_golden.jsonl`（389 → 1310，多轮 9 → 260）；多轮 B 的 case 级 expected 用 `any_turn` 作用域；空轮 case 标 `skip_reason` 显式跳过；lint 同守两份文件并列出数据缺陷；`ai_test_langgraph` 标 deprecated | `harness/golden.py`、`harness/differ.py`、`harness/cli.py`、`scripts/langfuse/langfuse_eval.py`、`scripts/check_fixture_consistency.py`、`tests/fixtures/README.md`、`tests/test_harness.py`、`tests/test_fixture_consistency.py` | 第五节 R2 / R5 / R8（主力数据集与主力工具不兼容、三套评估台、多轮 2.3%）|
| **阶段 1 · harness 判定口径收口**：REJECTED 单独桶不算 PASS；早停后未执行轮逐轮记失败；`/health.backend_mode` + `--backend` 把关（dry-run 真生效） | `harness/cli.py`、`harness/differ.py`、`app/api/health.py`、`tests/test_harness.py`、`tests/observability/test_health_probes.py` | 第五节 R9（假绿）、R12（假开关）|
| **阶段 2 · RetryPolicy + 客户端单例 + BotContext**：`@io_node` + `add_io_node` 给 16 个只读 IO 节点挂 RetryPolicy 与耗尽兜底，14 个写类节点不重试（清单守护）；lifespan 级 httpx 连接池，四个 Client 复用；`BotContext` 取代三份 `_context` | `app/graph/retry.py`、`app/graph/safe_node.py`、六个 graph builder、`app/tools/http_pool.py`、`app/tools/bot_context.py`、四个 `*_client.py`、三个 `backend.py`、`app/main.py`、`tests/graph/test_retry_policy.py`、`tests/tools/` | 第二节 2.2（RetryPolicy 零使用、客户端每请求新建、协议层吃整个 AgentState）|
| **阶段 2 · `extract_inquiry` 拆子图 + `last_confirmed_params`**：询价三管线做成图边（7 阶段节点，错误归因到阶段）；ConversationMemory 写入节点 `remember_confirmed_params` + 六个确认节点裸确认回退读记忆（显式引用 / 单号优先） | `app/subgraphs/option/extract_inquiry.py`、`app/graph/memory.py`、`app/nodes/remember_confirmed.py`、`app/graph/main.py`、`app/graph/state.py`、swap / option / close 确认节点、`tests/subgraphs/option/test_extract_inquiry_graph.py`、`tests/graph/test_memory.py`、`tests/nodes/test_remember_confirmed.py` | 第二节 2.1（`extract_inquiry` 3 管线厚节点）、第三节（checkpoint 只写不读、确认链路从文本重抽单号）|
| **阶段 2 · 节点延迟直方图 + 结构化日志**：`otc_agent_node_latency_ms{node}` 独立指标，删 alerts 的 `node=` 过滤 hack；`@safe_node` 单一计时补 `elapsed_ms`；structlog 接管 stdlib，`LOG_LEVEL` / `LOG_FORMAT` 生效，请求级 `trace_id` / `conversation_id` / `message_id` 经 contextvars 进每条日志 | `app/observability/metrics.py`、`app/observability/alerts.py`、`app/graph/safe_node.py`、`app/observability/logs.py`、`app/api/routes.py`、`app/main.py`、`app/config.py`、`docs/observability.md`、`tests/observability/test_logs.py`、`tests/graph/test_safe_node_timing.py` | 第四节 P1-3（节点延迟寄生）、P1-4（无结构化日志无 trace_id）、P2（elapsed 三套 / duration_ms NULL）|
| **阶段 3 · Dify 残留 B / C 级清理**：tag 冻结后移除 dify/、导出脚本、两技能两 agent 及镜像、rerank 桩与明文 key、零流量 v2、dify-originals（-2.8MB）；19 份 `.md` 去元数据行、12 份死 `[user]` 段删除、占位符原生化 | `app/prompts/**`、`app/subgraphs/ticker/tools.py`、`app/subgraphs/close/holding_query.py`、`app/subgraphs/swap/multimodal.py`、`app/subgraphs/swap/fresh_counterparty.py`、`mock_api/server.py`、`tests/api/_utils.py`、CLAUDE.md / README / 规则 / ADR 口径 | 第六节 B3 / B4 / B5 / B6 / B12 / B13、C1 / C2 / C3 / C5 / C6 / C7 / C8 / C9 / C10 / C11 |

**未在本环境落地、需团队决策或真实环境**：CI 触发恢复（团队 2026-05-12 主动暂停，用户指示暂缓）、revoke 明文 Dify API key（用户指示暂缓）、连接池 / 幂等在真实 MySQL / TDSQL 上的验证、`history_messages` 窗口 N 与重构 6 的现场 eval 校准、`outputs.place_params.expected_action` 投影的下线时机（需确认无外部读者）、`POST /v1/runs`（需 Java 联动）。

## 附录 A · 五路评审证据索引

各路完整报告（含全部 `file:line`）由评审代理生成，主评审已复核以下关键结论：`harness/differ.py:81` 别名 bug、`ci.yml` 仅 `workflow_dispatch`、`emit_llm_*` 零调用、`from_conn_string` 单连接、`tests/api/_utils.py:12` 明文 key、`render.py:247/249` 无 intent 守卫、`unified_golden.jsonl` 加载报错、`history_messages` 无窗口、`route_rules.py:8` 纪律条文。
