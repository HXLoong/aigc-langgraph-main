# ADR 0001 · 推倒重写 `app/`，按 Harness-first 范式落实 LangGraph 替换 Dify

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Tony

## Context

`app/` 下当前代码是早期 Claude Code 自动生成的迁移骨架，存在结构性问题：
- 与真实 Dify 主干工作流的节点划分不一一对应（互换 12 个 LLM 节点 / 期权 7 个 LLM 节点的实际结构没被精确还原）
- 对 Java Worker 的契约不明确
- 缺少独立可 replay 的节点接口，Harness 无法自驱
- 测试覆盖按"代码先有，再补测试"的传统顺序，违反 Harness-first 的"case 先于实现"原则

迁移目标已经在 CLAUDE.md 钉死：用 LangGraph 替换 Dify。当前代码距离这个目标有明显工程债。

## Decision

### D1 · 推倒边界

| 处置 | 内容 |
|------|------|
| 保留 | `app/prompts/` (23 个 .md，Dify 原封资产) · `app/llm/clients.py` · `app/checkpointer/factory.py` · `dify/sync.py` + `dify/yaml/` · `mock_api/server.py` · `tests/fixtures/golden.jsonl` |
| 重写 | `app/state.py` · `app/graphs/` · `app/subgraphs/` · `app/nodes/` · `app/tools/` · `app/api/routes.py` · 大部分 `tests/test_*.py` · `scripts/` |
| 新增 | `harness/` 顶层目录（评测台，与 `app/` 解耦） |

### D2 · `tools/` 层的契约策略

> **2026-05-10 修订**：原方案按"业务领域"拆 4 个 Protocol（QuoteClient / OrderClient / PositionClient / TickerClient）。审计真实 Java 契约后调整为**按真实 endpoint 边界**拆 3 个 Protocol。理由见末尾。

`tools/` 重写时**直接对齐 Java 后端真实业务 API 契约**（已挖出，见 `docs/api-contracts/java-backend.md`）：

| Protocol | 覆盖范围 | 真实 endpoint |
|----------|----------|---------------|
| `OptionClient` | 期权全流程（询价 / 下单 / 改单 / 撤单 / 平仓 / 查询，含 16 种意图）| `POST /admin-api/financial-orders/operate` + `POST /admin-api/financial-orders/query-close-orders` |
| `SwapClient` | 互换全流程（下单/改单 / 撤单 / 确认 / 查询，7 种意图） | `POST /admin-api/swap-order/operate` + `GET /admin-api/swap-order/get` + `POST /admin-api/swap-order/get-conversation-orders` |
| `TickerClient` | 标的查询 / 动态推断 prompt / 交易对手列表 | `GET /admin-api/integration/securities-instrument/select` + `GET /admin-api/counterparty/info/instrument-inference-prompt` + `GET /admin-api/counterparty/info/list` |

工程纪律：
- 每个 Protocol 的入参出参用 **Pydantic 模型**定义，字段名和类型严格匹配 Java DTO（`placeOrderWindCode`, `placeOrderQuantityHand` 等保留 Java 风格命名以便 1:1 对照）
- **type 字段**对应 Java enum：互换用 `SwapIntentionType`（7 值），期权用 `stockOptionIntentionType`（16 值）；LangGraph 这边定义 Pydantic `Literal` 类型严格约束
- 金额字段一律用 `Decimal`，向 Goats 发送前 `truncate(2)`（对齐 `TradePrecisionUtil.truncateOrderScale()`）
- 调用方只依赖 Protocol，不依赖具体实现
- 当下用 mock_api 实现 Protocol（保持闭环可跑）；联调阶段用 httpx 实现替换，调用方零改动
- 机器人上下文（`conversationId / messageId / userId / roomId / ...`）由 ingest 节点从 Dify Workflow Run inputs 解析后存入 AgentState，再由具体节点透传给 OptionClient/SwapClient

调整理由：Java 后端是"按 endpoint 聚合"的设计——`/financial-orders/operate` 一个接口处理期权所有 16 种意图；`/swap-order/operate` 一个接口处理互换 7 种。如果按"业务领域"切（QuoteClient / OrderClient / PositionClient），Pydantic 模型会与 Java DTO 不一一对应，反而更难维护。**Protocol 边界跟随 endpoint 边界**是正确的契约策略。

边界问题（已解）：标的查询的归属问题已通过 D4 解决——直接调既有 endpoint，无需 Java 新开接口。

### D4 · 标的查询职责归 LangGraph（**已存在 endpoint，无需新开**）

> **2026-05-10 修订**：原 D4 提出 "Java 暴露新 HTTP `POST /openapi/instrument/search`"。审计 Java 源码后发现 **endpoint 已经存在**——`SecuritiesInstrumentController.java:100` 已经暴露了 `GET /admin-api/integration/securities-instrument/select`。**Java 团队无需新开接口**，LangGraph 直接调既有接口即可。

LangGraph ticker 子图（ReAct Agent，见 D6 + ADR 0008）通过 `TickerClient` 调用既有 endpoint：

```
GET /admin-api/integration/securities-instrument/select
Body: { keywordItems: [{keyword: str, isFull: bool}], transactionTypeList?: list[str] }
Resp: List<SecuritiesInstrumentOpenApiRespVO>
   { windCode, insShtDesc, insLngDesc, relevanceScore, transactionTypeLists }
```

⚠️ **注意**：这是 GET + RequestBody 设计（不规范但合法）。tools 层 httpx 实现要支持 GET-with-body：

```python
await client.request("GET", url, json=payload)  # 不是 client.get()
```

理由（保持原 D4 的论据）：
- CLAUDE.md 钉死"标的代码必须 from_goats=True"——LangGraph 必须自己校验，不能信任 Java 预解析
- 现有 LangGraph ticker 子图（ReAct Agent）已经存在，选 Java 预解析等于作废它
- 共享数据库（LangGraph 直连 DB）是架构反模式
- HTTP 跳转 5-20ms 对 LLM 链路总耗时可忽略
- harness 视角：让 `TickerClient` 成为干净可 mock 的 Protocol，bug 可在 harness 内复现

交易时间查询（`queryTradingHours`）当前是 Java 内部 helper（非 HTTP），不在已暴露的 endpoint 列表里。M1 阶段 `TickerClient` 接口先留 stub；M2/M3 阶段如真用到，再决定是请 Java 暴露 HTTP 还是 LangGraph 自己用启发式时间表。

**Java 团队工作量调整**：从原"暴露 1 个新接口"降为 **0**。整条 D4 不需要 Java 团队配合发版。

### D5 · 节点合并策略：保守路 A+ 加 option 拆分（按真实 Java 意图枚举调整）

> **2026-05-10 修订（二次）**：option 拆分按 grill-with-docs 复盘订正为 **5 个 extract**（不含 `extract_close`）。原 6 个版本错误地把 close_order_* 意图算进 option，但 close 是独立子图。详见 ADR 0011 二次修订。

逻辑层与 Dify **大部分 1:1**，但有两处定向重构：

| 处置 | 内容 | 来源 |
|------|------|------|
| **合并** | 互换-节点-确认下单 (129) + 互换-节点-确认撤单 (128) + 互换-节点-确认改单 (128) → 1 个 `swap.confirm(expected_action)`，新写统一 confirm 提示词 | 本 ADR |
| **拆分** | 期权-意图识别、参数提取（2870 行单节点）→ 1 个 intent 节点 + 5 个 extract 节点（按 Java 真实 10 个 option 基础意图按职责合并；6 个 close_order_* 归 close 子图） | 沿用 ADR 0011（二次修订）|
| **瘦身** | `app/prompts/swap/place_order.md`（约 133K 字符 / 40K tokens）M3 期间允许结构化精简（删冗余示例、压缩重复规则），保留语义；理由：超过 Qwen3-30B 上下文的 50%，存在截断正确性风险，不能等 shadow PASS 再动 | 2026-05-12 grill |
| **保持** | 其他 Dify LLM 节点 | 1:1 复刻，提示词照搬 |

option 5 个 extract 按职责合并：`extract_inquiry` / `extract_place_or_modify` / `extract_cancel` / `extract_confirm` / `extract_query`。

最终节点数（grill-with-docs 2026-05-10 修订）：

| 子图 | 节点数 | 备注 |
|---|---|---|
| swap | 10 | 含合并后的 confirm 节点 |
| option | 6 | 1 intent + 5 extract |
| option_close | 7 | intent + place_close + holding_query + confirm_close + confirm_cancel + cancel_close + query_status |
| ticker | 1 | ReAct Agent 子图 |
| **合计** | **24 LangGraph 节点**（其中 23 个常规 LLM 节点 + 1 个 ReAct 子图）|

> **重要差异**：互换的"下单 vs 改单"在 Java 端**共用同一个 `place_order_request` 类型**（靠 `orderList[i].orderId` 是否存在区分），不是独立意图。LangGraph 子图设计也照此处理——swap.place_order 节点同时承担 placement + modification，由 OrderClient 决定 `orderId` 字段。

option 拆分理由（沿用 ADR 0011）：
- option intent_extract.md 是当前最大的提示词（2870 行 ≈ 1 KB tokens），是用户体验差的最大单一根因
- 准确率天花板已触顶；Dify 原设计本身不合理，不应背着这个债重写
- 重构期是修这条债的最佳窗口
- 拆分后每个 extract 提示词 < 500 行，可读、可调、harness 比对粒度更细

option 拆分使 D5 不再是单纯的"1:1 复刻 + 1 处合并"，而是"对 Dify 设计本身不合理处做定向重构"。这个范畴边界要严格守住——其他 15 个节点不再扩散重构。

工程层全新做：
- 每个节点是一个 `@safe_node` 装饰的 async 函数
- 入参从 `AgentState` 取明确字段，出参是 partial state dict（不 mutate）
- LLM 调用走 `with_structured_output(<NodePydanticOutput>)`
- 提示词从 `app/prompts/<category>/<name>.md` 加载（`load_prompt`）
- 节点函数纯函数化，harness 可单独 replay
- trace 字段记录节点名 / 决策 / 关键字段

不走更激进合并的理由：
- 用户最痛的 3 件事（标的不准 / 参数 bug / 评估缺失）不靠节点合并解决——分别靠 ticker 算法、Pydantic 契约、harness
- 激进合并（3 个下单输入合 1）会把 2831 行提示词压到 1500-2000，信息密度过载反而更易漂移
- shadow 双跑迁移期靠"节点级 diff"定位差异，节点变少 diff 颗粒度变粗

CLAUDE.md 纪律调整（重构期内）：
- "不碰 Dify 原始提示词内容" → **暂停**，合并/新写需在 ADR 0001 D5 表格中登记
- "修改 `app/prompts/**/*.md` 的内容" 从"绝对禁止"列移除（重构期内）
- 重构完成（shadow PASS）后恢复纪律，新提示词进入"只读资产"状态

逻辑层进一步清理（如下单 3 输入合并）作为后续 ADR 处理，不在 0001 范围。

### D6 · 目录结构 + AgentState 设计

```
app/
├── api/routes.py                  # 兼容 Dify Workflow Run API（POST /v1/workflows/run）
├── graph/
│   ├── main.py                    # 主图组装 + 一级路由
│   ├── state.py                   # AgentState
│   └── safe_node.py               # @safe_node 装饰器
├── nodes/
│   ├── ingest.py                  # Dify inputs → state
│   ├── intent_route.py            # 一级路由 swap/option/close
│   ├── persist.py                 # 写 trace 到 MySQL
│   └── render.py                  # state → Dify outputs
├── subgraphs/
│   ├── swap/                      # 10 节点（合并 3→1 后）
│   │   ├── graph.py
│   │   ├── intent.py
│   │   ├── place_order.py
│   │   ├── place_order_image.py
│   │   ├── place_order_excel.py
│   │   ├── confirm.py             # 合并节点（覆盖原 3 个确认 X）
│   │   ├── cancel.py
│   │   ├── cancel_extract.py
│   │   ├── query_order.py
│   │   ├── image_recognize.py
│   │   ├── hand_to_share.py
│   │   └── models.py              # 该子图所有 Pydantic Output
│   ├── option/                    # 6 节点（1 intent + 5 extract，沿用 ADR 0011 二次修订）
│   │   ├── graph.py
│   │   ├── intent.py              # 新写：仅意图分类（< 500 行 prompt）
│   │   ├── extract_inquiry.py     # 新写：询价参数提取（new_inquiry）
│   │   ├── extract_place_or_modify.py  # 新写：下单/改单参数（共用 schema，靠 expected_action 区分）
│   │   ├── extract_cancel.py      # 新写：撤单参数提取（cancel_order_request + request_cancel_order）
│   │   ├── extract_confirm.py     # 新写：3 种确认参数提取（confirm_order/cancel/modify）
│   │   ├── extract_query.py       # 新写：查询参数提取（query_order_status）
│   │   └── models.py              # 6 个 Pydantic Output（intent + 5 extract）
│   ├── close/                     # 6 节点
│   │   └── {graph,intent,place_close,confirm_close,confirm_cancel,
│   │        holding_query,query_status,models}.py
│   └── ticker/                    # 1 节点 = ReAct Agent 子图（沿用 ADR 0008）
│       ├── graph.py               # ReAct Agent 编译入口
│       ├── react_agent.py         # 单一 LangGraph 节点：调度 LLM + 工具循环
│       ├── tools.py               # 4 个工具函数（tokenize / completeness / rank / infer_code 调用）
│       └── models.py              # 工具入参出参 + 最终 TickerCandidate 输出
├── tools/
│   ├── quote.py                   # QuoteClient Protocol + impl
│   ├── order.py                   # OrderClient
│   ├── position.py                # PositionClient
│   ├── ticker.py                  # TickerClient
│   └── models.py                  # Java DTO 对应 Pydantic
├── llm/clients.py                 # 保留
├── checkpointer/factory.py        # 保留
├── prompts/                       # 保留 + 新增 swap/confirm.md
└── config.py

harness/                            # 与 app/ 解耦，仓库根目录
├── runner.py
├── differ.py
├── reporter.py
├── golden.py
└── cli.py                         # python -m harness <cmd>
```

工程纪律：
1. **一节点一文件** — Dify LLM 节点 → 1 个 .py，单一职责，50-150 行
2. **测试一对一** — `tests/subgraphs/swap/test_place_order.py` 对应 `app/subgraphs/swap/place_order.py`
3. **harness 只 import `app.graph.main.build_main_graph`** — 不依赖任何节点内部，app 重构时 harness 不用改

`AgentState`（按业务对象聚合，不按节点输出扁平铺）：

```python
class AgentState(TypedDict, total=False):
    # 入口
    raw_text: str
    conversation_id: str
    history_messages: Annotated[list[Message], add]
    
    # 业务路由（ProductType 4 类，详见 ADR 0015）
    product_type: Literal["swap", "option", "option_close", "unknown"]
    intent: str  # 二级意图（place_order / cancel_order / query / ...）
    
    # 业务对象（聚合，多节点共享同字段）
    tickers: list[TickerCandidate]
    place_params: SwapPlaceParams | OptionPlaceParams | None
    cancel_params: CancelParams | None
    confirm: ConfirmResult | None  # 合并节点输出：{action, is_confirmed, reason}
    query_filter: QueryFilter | None
    close_params: ClosePositionParams | None
    
    # 工程层
    trace: Annotated[list[TraceEntry], add]
    error: ErrorInfo | None
```

理由：harness 比对按业务对象做 `==`，不需要逐节点比对中间产物；3 个原确认节点合并后只占用 1 个 state 字段；新增意图只需加业务对象字段，不破坏现有结构。

### D7 · Harness 失败报告格式（AI 工具友好）

> **2026-05-10 修订**：本节原设计自定义 JSON 报告。引入 LangFuse 后（见 ADR 0014）简化为：
>
> - **机器读** = LangFuse Trace API（含完整 span 树 + token + latency + 字段级 metadata），AI 工具用 LangFuse SDK 拉
> - **人读** = LangFuse UI（trace 树 + diff + score）
> - **suspected_node / suspected_prompt** = harness reporter 写薄薄一个启发式层（"diff 字段的最后写入节点"），从 LangFuse trace 读出后附在 trace metadata 里
> - **CI 离线场景** = 仍输出下面的 JSON 作为 fallback（LangFuse 不可用时）
>
> 下面的 JSON 结构作为 fallback / CI 标准格式保留：

每条失败 case 输出一份 JSON（机器读）+ 一份 markdown（人读）。JSON 结构：

```json
{
  "case_id": "g042",
  "raw_content": "...",
  "expected": { "intent": ..., "product_type": ..., "params": {...} },
  "actual":   { "intent": ..., "product_type": ..., "params": {...} },
  "diff": [
    {"path": "params.price_type", "expected": "limit", "actual": "market"}
  ],
  "trace": [
    {"node": "swap.place_order", "decision": "...", "elapsed_ms": 3217,
     "llm_input_excerpt": "...", "llm_output": {...}}
  ],
  "suspected_node": "swap.place_order",
  "suspected_prompt": "app/prompts/swap/place_order.md"
}
```

四个关键设计：
1. `diff` 用字段级路径数组，不是字符串 unified diff——AI 读字段路径比读 diff 块快 100×
2. `trace` 每节点记 `llm_input_excerpt` + `llm_output`，定位到具体 LLM 调用的输出
3. `suspected_node` 用启发式："diff 字段所在的最后一个写入它的节点"
4. `suspected_prompt` 给出 .md 文件路径，Claude Code 可直接 `Read` + `Edit`

Markdown 配套报告：汇总统计 + 失败列表 + 各节点失败率 top 5（人审查用）。

### D8 · 上线节奏（4 里程碑）

> **Status update (2026-05-11，由 ADR 0016 修订)**：M3 含义重定义为"工程联调闭环（真后端 + 真 LLM）"，**不再是 shadow 双跑**。Shadow 双跑改名为 **F4.1**，作为 M4 阶段 4 的第一步，详见 ADR 0016 + `docs/m3-m4-roadmap.md`。下表 M3 行的"Shadow 双跑（2 周）"已过期，以 ADR 0016 为准。

| 里程碑 | 内容 | 退出条件 |
|--------|------|----------|
| **M1 · 骨架（1-2 周）** | 新 `app/graph` + `state.py` + 4 个 `tools/` Protocol（mock_api 实现）+ harness MVP（runner / differ / golden loader / cli） | 30 条现 golden 跑通，全 PASS |
| **M2 · 子图实现（3-4 周）** | 24 个 LangGraph 节点逐个实现（swap 10 + option 6 + option_close 7 + ticker 1）；每节点 5-15 条 golden；按 D9.1 半串行 schedule | D9.2 退出门表（P0 golden ≥ 80，ticker PASS ≥ 90%，三链路 PASS ≥ 85%）|
| **M3 · ~~Shadow 双跑（2 周）~~ 工程联调闭环**（ADR 0016 修订）| ~~LangGraph 暴露 `/v1/workflows/run`；shadow 工具同时打 Dify + LangGraph diff~~ → 真后端 D2.* 联调 + harness E3.* 真 LLM 评测 + F4 灰度工具链就绪 | ~~主要意图 diff 率 < 5%；下单/平仓 < 1%~~ → 见 ADR 0016 + roadmap 阶段 3 退出门 |
| **M4 · 金丝雀切换（持续）** | Java 配 `agentUrl` 5% → 25% → 50% → 100%；harness 在线持续监控 + F4.1 shadow 双跑（M3 转过来的） | 100% 流量 + 7 天无重大事故（ADR 0017 量化退出门 + ADR 0019 故障升级阈值）|

每里程碑后开 review，不达标停在原阶段补窟窿。

### D9 · M2 节点实现优先级

按业务关心度分三档：

```
P0（最先做）：
  - swap.place_order（1459 行最大节点）
  - option.intent_extract（期权下单 + 询价）
  - close.place_close
  - ticker 子图（CLAUDE.md 硬约束）

P1（参数 bug 关键）：
  - swap.cancel + cancel_extract
  - swap.confirm（合并版）
  - swap.query_order
  - close.confirm_close + confirm_cancel + holding_query

P2（边角）：
  - swap.place_order_image / place_order_excel
  - swap.image_recognize
  - swap.hand_to_share
  - close.query_status
```

P0 跑通即可进 M3；P1 P2 可与 M3 并行。

#### D9.1 · P0 执行 schedule（grill-with-docs 2026-05-10）

**半串行 + 双轨 ticker**：

- **Week 1 · ticker 子图独占**：4-5 个 PR（骨架 → tokenize → completeness/rank → infer_code → 端到端 ReAct）。退出门 = 30+ 条 ticker-only golden，PASS ≥ 90% + 100% `from_goats=True`
- **Week 2-3 · 三节点并行**：swap.place_order / option (intent + extract_place_or_modify) / close (intent + holding_query + place_close) 三条链路并行；节点 PR 默认用真 ticker 跑 golden
- **双轨 ticker**：harness 提供 `--mock-ticker` 开关，CI / pre-commit 用 mock（白名单 50 个固定代码应答），shadow / 周回归用真 ticker。CI 全集 < 1 分钟

#### D9.2 · P0 退出门（M2 → M3 转场硬条件）

| 条件 | 阈值 |
|---|---|
| ticker 子图 ticker-only golden | PASS ≥ 90% + 100% `from_goats=True` |
| swap.place_order 节点 golden | PASS ≥ 85%（含真 ticker 链） |
| option intent + extract_place_or_modify 联合 | PASS ≥ 85% |
| close.place_close + intent + holding_query 联合 | PASS ≥ 85% |
| 总 P0 golden 数量 | ≥ 80 条（每节点至少 10-15 条） |
| `python -m harness run` 全集 | 无 crash，全部能产出 trace |

~~shadow 阶段（M3）~~ **shadow 阶段（F4.1，已被 ADR 0016 从 M3 移到 M4）**的"主要意图 diff < 5% / 下单平仓 < 1%"是更严的退出门，不在 P0 范围。

### D3 · LangGraph 暴露给 Java Worker 的协议

LangGraph 暴露 `POST /v1/workflows/run`，**完全模拟 Dify Workflow Run API**：
- Body: `{ inputs: {...}, response_mode: "blocking", user: "<conversation_id>" }`
- Response: `{ workflow_run_id, task_id, data: { outputs: {...}, status: "succeeded", ... } }`
- `inputs` 字段透传 Java 当前发给 Dify 的 schema（待 D5 详查具体字段）
- `outputs` 字段对齐 Java 当前从 Dify 解析的 schema

仅支持 **blocking** 模式（已核对：`StockBotMessageServiceImpl.java:1646` 写死 blocking，不走 streaming/SSE）。

理由：迁移期 shadow 双跑需要协议一致；回滚到 Dify 仅需改 `agentUrl` 配置；Java 团队解耦不需要跟着发版。等 LangGraph 跑稳后可开第二个 ADR 升级到干净协议。

## Alternatives

### 替代 1：增量改造现有 `app/`

**做法**：保留当前目录结构，逐节点重构、加 harness 接口、改进 state schema。

**风险**：
- 当前节点划分本身不对齐 Dify（互换 12 节点 / 期权 7 节点的真实结构没被精确还原）——增量改造会一直背着这笔工程债
- AgentState 字段是按节点输出扁平铺，不是按业务对象聚合，增量改要在大量节点中做侵入性改动
- 现有 `tools/otc_backend.py` 是 god class，按 mock_api 反推，没对齐 Java 真实契约——同样要大改
- "增量"在节点级别没有清晰边界——同时存在新旧节点会让 harness 设计变复杂
- 30 条 golden 是端到端的，没有节点级 case，增量改造的回归基线不够

**为什么不选**：节省的工作量被"边改边背债"抵消；项目处在迁移期，正好是推倒重写的窗口。

### 替代 2：路 B 激进合并（19 节点 → 5-6 节点）

**做法**：按"领域模型"重新设计，所有"参数提取"节点合并为一个大 LLM 节点 + 业务模型选择。

**风险**：
- 提示词需要 80% 重写，2831 行（下单 3 输入合计）压到 1500-2000 行，信息密度过载
- shadow 双跑无法 1:1 对比，迁移期定位差异成本翻倍
- 30 条 golden 远不够支撑"重设计后回归"
- 标的不准 / 参数 bug / 评估缺失三个核心痛点都不靠节点合并解决，激进合并属于"为了重构而重构"

**为什么不选**：边际收益低于风险；保守路 A+ 已经覆盖唯一值得合并的冗余（3 个确认节点）。

### 选择本方案的理由

- **逻辑层 1:1（仅合并 3 个确认）+ 工程层全新做** 是单位时间收益最大的组合
- 工程层（Pydantic 契约、@safe_node、可 replay 节点、harness）是 Harness-first 的本质，也是"改 bug 引新 bug"循环的真正解药
- 4 里程碑的小步节奏让每一步都有明确退出条件，风险逐级释放
- 节点级 1:1 让 shadow 双跑的差异定位精确到节点，迁移期可控

## Consequences

### 积极后果

- **AI 工具自驱迭代成为可能** — harness 输出的 JSON 直接喂给 Claude Code，可定位到 .md 文件并修改
- **bug 修复有回归基线** — golden 从 30 扩到 200+ 后，"修一个 bug 引一个新 bug"循环被打破
- **shadow 双跑可定位** — 节点级 1:1 让 diff 精确到具体提示词
- **联调阶段零阻塞** — tools/ Protocol 切换实现即可，调用方不动
- **新意图加入有模板** — 每个新意图按"`@safe_node` + Pydantic Output + .md 提示词 + golden case"四件套增量

### 消极后果与缓解

| 后果 | 缓解 |
|------|------|
| 重写 4-7 周内现有 `app/` 不可用 | 保留当前 main 分支可回切；新代码在 feature/rewrite-with-harness 分支推进 |
| Java 团队需配合 D4 暴露新 HTTP 接口 | M1 阶段同步推进，提前 2 周对齐 |
| `app/prompts/` 不再"只读"——重构期内 confirm.md 是新写的 | ADR D5 已登记；重构完成后纪律恢复 |
| harness 运行成本（LLM 调用）不便宜 | golden set 扩张时分类管理：smoke（每 PR 跑）/ full（每周跑）/ canary（线上抽样） |
| 4 里程碑总周期 7-10 周 | 保守估计；P0 跑通即可启动 M3，P1 P2 可并行 |

## Related

### 上下游 ADR

- **ADR 0000** · 元 ADR：从 Dify 迁到 LangGraph 的根本动机（4 痛点）。本 ADR 接管"如何重写"
- **ADR 0002** · Harness 三阶段目标（开发期 / 运行期 / 调优期）。本 ADR D7-D9 是其落地方案
- **ADR 0008** · ticker 用 ReAct Agent。本 ADR D6 中 ticker/ 子图按此设计（不是 4 个独立节点）
- **ADR 0011** · option 拆 1 + 7 节点。本 ADR D5 沿用此决定
- **ADR 0012** · 标的查询走后端 HTTP。本 ADR D4 是其精确化（指定新 endpoint `POST /openapi/instrument/search`）

### 配套不冲突的 ADR

- **ADR 0003** · 提示词 v1/v2 同目录并存（用于 confirm.md / option/extract_*.md 这些重写资产的版本管理）
- **ADR 0004** · trace 节点级 + LangSmith（D7 失败报告的运行时来源）
- **ADR 0005** · LLM judge + 业务方周抽检（M3+ 阶段的标注闭环）
- **ADR 0006** · HITL interrupt 边界（节点函数实现 interrupt_before 时遵循）
- **ADR 0007** · 新意图 vs 新子图规则（M2+ 后续扩展按此判断）
- **ADR 0009** · MySQL / TDSQL 兼容（checkpointer 沿用既有约束）
- **ADR 0010** · Qwen 三型号分工（每个节点的 LLM 客户端按此选）
- **ADR 0013** · 加载后端动态 prompt 片段（ticker 子图 ReAct Agent 拼接 prompt 时遵循）
- **ADR 0014** · LangFuse 作为 Harness 后台服务（修订本 ADR D7 的失败报告格式；trace / dataset / eval / annotation 四件套统一）
- **ADR 0015** · 一级路由：规则前置 + LLM 兜底（精确化本 ADR D6 的 `intent_route` 节点实现，订正 ProductType schema）

### 引用资源

- `dify/yaml/主干工作流.yml` — 真实工作流（19 个 LLM 节点）
- `CONTEXT.md` — Harness / Golden case / Shadow compare 术语定义
- `docs/api-contracts/java-backend.md` — Java 业务 API 契约（D2 的依据）
- 架构图（用户提供，2026-05-10）
