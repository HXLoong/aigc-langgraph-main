# ADR 0001 · 推倒重写 `app/`，按 Harness-first 范式落实 LangGraph 替换 Dify

- 状态：已采纳（重写已完成，M1/M2 落地；本文含蓝图与落地的差异对照）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #139）
- 作者：图灵科技 + Tony

## 上下文（历史）

2026-05 时 `app/` 下代码是早期自动生成的迁移骨架，存在结构性问题：与真实 Dify 主干工作流的节点划分不一一对应（互换 12 个 LLM 节点 / 期权 7 个 LLM 节点的实际结构没被精确还原）、对 Java Worker 的契约不明确、缺少独立可 replay 的节点接口、测试按"代码先有再补测试"的传统顺序。迁移目标已在 CLAUDE.md 钉死：用 LangGraph 替换 Dify。

决定**推倒重写**，按 Harness-first 范式推进。重写已随 M1/M2 完成（M2 PR #41 合 main）。以下各节按"决策 + 落地现状"记述。

## Decision

### D1 · 推倒边界（含落地后修正）

| 处置 | 内容 | 现状备注 |
|------|------|---|
| 保留 | `app/prompts/`（现 **37 个**业务 .md）· `app/checkpointer/factory.py` · dify/sync.py + dify/yaml/（2026-09-17 随 ADR 0024 D1 移除，tag dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建））· `tests/fixtures/old_typing/golden.jsonl` | `app/llm/clients.py` 保留路径、**内容已按 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 重写**为 vendor 适配层 |
| ~~保留~~ 已下线 | `mock_api/server.py` | 2026-05-13 随"切换真实后端环境"删除（commit `4ac9f0b`），单测改 AsyncMock、e2e 走 `scripts/probe_*_e2e.py` 真后端探针 |
| 重写 | `app/graph/state.py` · `app/graphs/` · `app/subgraphs/` · `app/nodes/` · `app/tools/` · `app/api/routes.py` · `tests/` · `scripts/` | M1 的 M1 状态兼容模块（已删） 兼容 shim 与 `app/graphs/` shim 均已删除（2026-08-28 / 2026-09-17 ADR 0024），真源在 `app/graph/`，入口在 `app/api/turn_state.py` |
| 新增 | `harness/` 顶层目录（评测台，与 `app/` 解耦） | 已建成，模块清单见 [ADR 0002](./0002-comprehensive-runtime-harness.md) |

### D2 · `tools/` 层的契约策略（落地与蓝图一致）

按**真实 endpoint 边界**拆 3 个 Protocol（放弃早期"按业务领域拆 4 个"的方案；Java 契约见 `docs/api-contracts/java-backend.md`）：

| Protocol | 覆盖范围 | 真实 endpoint |
|----------|----------|---------------|
| `OptionClient`（`app/tools/option_client.py`）| 期权全流程，16 种意图 | `POST /admin-api/financial-orders/operate` + `POST /admin-api/financial-orders/query-close-orders` |
| `SwapClient`（`app/tools/swap_client.py`）| 互换全流程，7 种意图 | `POST /admin-api/swap-order/operate` + `GET /admin-api/swap-order/get` + `POST /admin-api/swap-order/get-conversation-orders` |
| `TickerClient`（`app/tools/ticker_client.py`）| 标的查询 / 动态推断 prompt / 交易对手列表 | `GET /admin-api/integration/securities-instrument/select` + `GET /admin-api/counterparty/info/instrument-inference-prompt` + `GET /admin-api/counterparty/info/list` |

工程纪律（全部落地）：

- 入参出参用 Pydantic 模型，字段名严格匹配 Java DTO（`placeOrderWindCode` 等保留 Java 风格命名）
- type 字段对应 Java enum：`SwapIntentionType` 7 值 / `stockOptionIntentionType` 16 值，Pydantic `Literal` 严格约束
- 金额一律 `Decimal`，发送前 `truncate(2)`（对齐 `TradePrecisionUtil.truncateOrderScale()`）
- 调用方只依赖 Protocol；实现现仅存 `*Httpx` 真后端实现（mock 实现随 mock_api 下线）
- 机器人上下文（conversationId / messageId / userId / roomId ...）由 ingest 节点解析后存 AgentState 透传

理由：Java 后端是"按 endpoint 聚合"的设计，Protocol 边界跟随 endpoint 边界，Pydantic 模型才能与 Java DTO 一一对应。

### D3 · 暴露给 Java Worker 的协议（落地一致）

`POST /v1/workflows/run` 完全模拟 Dify Workflow Run API（`app/api/routes.py`），仅支持 **blocking**（Java 侧 `StockBotMessageServiceImpl.java` 写死 blocking，核查时行号已漂移至 :1885）。迁移期协议一致 → 回滚只需改 `agentUrl`；跑稳后如需干净协议另开 ADR —— **已另开：[ADR 0024](./0024-langgraph-native-rearchitecture.md) D7（原生 `POST /v1/runs`，Dify 形态降为回滚期 adapter）**。

### D4 · 标的查询职责归 LangGraph（endpoint 已存在，Java 工作量 0）

审计 Java 源码确认 endpoint 已存在：`SecuritiesInstrumentController.java:100` `GET /admin-api/integration/securities-instrument/select`（GET + RequestBody，不规范但合法）。httpx 实现用 GET-with-body：`await client.request("GET", url, json=payload)`（已落地于 `app/tools/ticker_client.py`）。

理由：CLAUDE.md 钉死"标的代码必须 `from_goats=True`"，LangGraph 必须自己校验；直连 DB 是反模式；HTTP 跳转 5-20ms 对 LLM 链路可忽略；`TickerClient` 是干净可 mock 的 Protocol。`queryTradingHours` 至今未实现（决策未推进，仍无需求）。

### D5 · 节点合并策略：保守路 A+ 加 option 拆分

逻辑层与 Dify 大部分 1:1，两处定向重构 + 一处瘦身：

| 处置 | 内容 | 登记 |
|------|------|---|
| **合并** | 互换 3 个"确认 X"节点 → 1 个 `swap.confirm(expected_action)`，新写统一 confirm 提示词（`app/subgraphs/swap/confirm.py`） | 本 ADR |
| **拆分** | 期权 intent_extract（2870 行单节点）→ 1 intent + 5 extract（`extract_inquiry` / `extract_place_or_modify` / `extract_cancel` / `extract_confirm` / `extract_query`；close_order_* 归独立 close 子图） | [ADR 0011](./0011-split-option-intent-and-extraction.md) 二次修订 |
| **询价补参修复** | `option/intent.md`：期限补充归 `new_inquiry`，建仓补参/确认/撤单按动作和业务阶段判断，删除引用卡片关键词强制改写意图的后处理；`extract_inquiry.md` 增加可选原单号 `orderId`；`extract_place.md` 保留可选期限 `tenor`，原单号与新增期限同传，缺省参数由 Java 合并；保留冻结的 `intent_extract.md` | 2026-09-07 用户明确授权；两轮 HTTP + checkpoint + Java HTTP 请求回归，见 [API 契约](../api-contracts/java-backend.md) |
| **回归当前 Dify 原文** | 将 `option/{intent,extract_inquiry,extract_place}.md` 与 `swap/{intent,place_order,select_counterparty,select_ticker}.md` 的 system/user 提示词完整同步为 `dify/yaml/场外交易-test.yml` 对应 LLM 节点的 `prompt_template`，移除上述文件相对当前 Dify 工作流的本地提示词改写 | 2026-09-11 用户明确要求；`tests/prompts/test_prompt_governance.py` 按 node_id 锁定 7 个提示词与 YAML 一致 |
| **瘦身** | `app/prompts/swap/place_order.md`：Dify 原版 3059 行 / 152,546 字符 → **2249 行 / 126,171 字符**（删冗余示例、压缩重复规则，保留语义；原版存为 `place_order.dify_original.md`）。注：DSL v2（2026-08）Dify 侧已自行重写该提示词，旧瘦身版随迁移被替换 | 2026-05-12 grill 授权，M2/M3 执行，本次补登记 |
| **瘦身 P0 批（2026-08-28）** | 客户反馈提示词冗长/规则写死损害泛化性，全量评估见 `docs/swap-prompt-slimming-assessment.md`。P0 零风险档产出 4 个 v2 共存文件：`swap/{intent,image_extract,excel_extract,image_ocr}_v2.md`——只删死重（JSON 格式禁令，structured output 已强制）、悬空规则（bot_name_list/shortname_list/序号/total 等未注入变量）、重复陈述（同一规则 2~9 遍收敛为 1 处权威表述）、自相矛盾的补丁修订史（"POV 空格"）；**业务规则语义不变**。灰度经 `_versions.yaml`/env 控制，默认 0 流量，eval PASS ≥ v1 基线后方可放量（ADR 0003） | 本 ADR + 评估报告 |
| **去 LLM 化（2026-08-28 瘦身 P1）** | swap 撤单/查单/三确认共 5 个节点的唯一任务是提取 `H-` 订单号，改为确定性提取（`app/subgraphs/swap/order_id.py`，来源优先级 1:1 对照原提示词规约）；省 5 次 LLM 调用（≈4.8K tokens/请求）与幻觉面。5 个提示词转非活跃资产保留。二次校验/后端调用/输出形状不变 | 本 ADR + 评估报告 |
| **治理机制（2026-09-15）** | 客户反馈提示词臃肿 → 全域可维护性评估（`docs/prompt-maintainability-assessment.md`）；资产状态（active / gray / inactive）改由 ~~`app/prompts/_manifest.yaml`~~ + `scripts/prompt_inventory.py --check` 机器守护（2026-09-16 已废弃移除），本表只登记改写决定；删除零调用点的 `compose_prompt` 形态 | [ADR 0022](./0022-prompt-governance-after-code-migration.md) |
| **零风险瘦身批（2026-09-15，ADR 0022 D1 拍板后直接落 v1）** | 烘焙 Dify 常量节点 17797951842080 的 keywords / output（5 处悬空占位符）；删 structured output 节点的 JSON 格式禁令（swap 4 文件 + holding_query）；删 option 7 个 extract 的机器人过滤块与 query/bot_name_list 声明（代码不注入）；`ticker/infer_code.md` 删从未注入的范围限制段、名称→windCode 事实清单改格式占位（C-01 红线）；删 `swap/intent_v2` / `place_order_v2`。逐文件记录曾见 ~~`_manifest.yaml`~~ 的 `changelog`（已随 ADR 0022 废弃移除，2026-09-16） | [ADR 0022](./0022-prompt-governance-after-code-migration.md) D4 |
| **回归副作用补齐（2026-09-15）** | 09-11 回归把 Dify 靠 code 节点前置分流的「确认下单」从 `swap/intent.md` 枚举中移除，app 未移植分流 → 确认下单链路不可达；已在 `app/subgraphs/swap/intent.py` 移植同款 `has_confirmation_keyword` 前置（不调 LLM）。同批：`select_counterparty.md` 把简写唯一性交给代码 → `aggregate.shortname_from_pick` 改「精确 → 唯一子串 → None」；ticker / holding_query 补齐 Dify 上游注入的 日期 / 对手列表 占位符渲染 | 评估 SW-INC-01 / SW-INC-06 / TRJ-01 / OC-01 |
| **保持** | 其他 Dify LLM 节点 1:1 复刻，提示词照搬 | — |

**节点数：蓝图 24 → 主干落地 20**（与 CLAUDE.md / README 口径一致）：

| 子图 | 蓝图 | 落地 | 差异说明 |
|---|---|---|---|
| swap | 10 | **6**（intent / place_order / confirm / cancel / query_order / unknown 兜底）| `place_order_image` / `place_order_excel` / `image_recognize` / `cancel_extract` 为 **P2 backlog**（按线上流量增量补）；`hand_to_share.py` 已实现**未接线** |
| option | 6 | 6（另有 unknown 兜底节点）| 与蓝图一致 |
| option_close | 7 | 7（另有 unknown 兜底）| 与蓝图一致 |
| ticker | 1（ReAct 子图）| 1 | ⚠️ 实为 resolver 确定性编排，见下"实现偏离" |

补充事实：`intent_extract.md`（2870 行）已冻结为 diff 快照，为非活跃资产；`place_order.dify_original.md` 已随 DSL v2 迁移（99a4c2f）删除。非活跃资产曾以 ~~`app/prompts/_manifest.yaml`~~ 为准（ADR 0022）；manifest 机制已于 2026-09-16 废弃移除。

互换"下单 vs 改单"共用 `place_order_request`，靠 `orderList[i].orderId` 有无区分（`swap/place_order.py` 落地一致）。

不走激进合并的理由（保留原论证）：用户最痛的三件事（标的不准 / 参数 bug / 评估缺失）分别靠 ticker 算法、Pydantic 契约、harness 解决，不靠节点合并；激进合并会让提示词信息密度过载、diff 颗粒度变粗。

提示词纪律：重构期内合并/新写/瘦身须在本表登记；M4 全量后恢复只读（[ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) 管版本化）。

### D6 · 目录结构 + AgentState（按落地现状重画）

```
app/
├── api/                       # routes.py（POST /v1/workflows/run）+ health.py
├── graph/
│   ├── main.py                # 主图组装 + 一级路由（_route_after_intent）
│   ├── state.py               # AgentState（真源；M1 shim 已删）
│   ├── safe_node.py           # @safe_node 装饰器
│   └── cascade.py             # cascade fallback 防御
├── nodes/                     # ingest / intent_route / persist / render / fallback
├── subgraphs/
│   ├── swap/                  # graph / intent / place_order / confirm / cancel /
│   │                          #   query_order / hand_to_share(未接线) / backend / models
│   ├── option/                # graph / intent / extract_*×5 / backend / models
│   ├── close/                 # graph / intent / place_close / cancel_close / confirm_close /
│   │                          #   confirm_cancel / holding_query / query_status / models（7 节点）
│   └── ticker/                # graph / react_agent(死代码) / tools(4 @tool) / resolver(生产路径)
├── tools/                     # option_client / swap_client / ticker_client（3 Protocol）
│                              #   + models / auth / exceptions / goats_rfq
├── llm/clients.py             # LLM 统一工厂（ADR 0020 vendor 适配层）
├── checkpointer/factory.py    # AIOMySQLSaver（已随 ADR 0021/#153 接线，use_mysql_checkpointer）
├── observability/             # tracing / metrics / alerts / canary / health_probes
└── prompts/                   # 41 个业务 .md + _versions.yaml（_manifest.yaml 已随 ADR 0022 废弃移除）
harness/                       # 评测台（模块清单见 ADR 0002）
```

工程纪律与落地情况：

1. **一节点一文件，50-150 行** —— 多数达标；越界豁免名单：`close/place_close.py` 280、`ticker/tools.py` 547、`ticker/resolver.py` 373、`option/extract_inquiry.py` 187、`swap/place_order.py` 179（软纪律，超 200 行需在 PR 说明）
2. **测试一对一** —— 实际按"意图组/链路"分组（如 `test_confirm_cancel_query.py` 覆盖 3 节点），语义等价
3. **harness 只 import `app.graph.main.build_main_graph`** —— ~~主链路成立~~（2026-09-16 核查：主链路已改 HTTP 调用，不再 import app 代码主图）；例外见"实现偏离"

`AgentState` 按业务对象聚合（`app/graph/state.py`）：`product_type`（Literal 4 值）/ `intent` / `tickers` / `place_params` / `cancel_params` / `confirm` / `query_filter` / `close_params` / `trace`（Annotated add reducer）/ `error`。理由：harness 按业务对象比对，新增意图只加字段不破坏结构。⚠️ 业务参数字段的类型现状见"实现偏离"。

### D7 · Harness 失败报告格式（LangFuse 版为准）

- **机器读** = LangFuse Trace API（完整 span 树 + token + latency + 字段级 metadata）
- **人读** = LangFuse UI
- **suspected_node / suspected_prompt** = ~~`harness/reporter.py`~~ 启发式层（"diff 字段的最后写入节点" + state 字段→节点→prompt 映射表）；该模块已从仓内移除（2026-09-16 核查）
- **CI 离线 fallback** = 本地 JSON（`.harness-runs/`），结构含 `diff`（字段级路径数组）/ `trace`（每节点 llm_input_excerpt + llm_output）/ `suspected_*`

四个关键设计不变：字段级 diff 比 unified diff 快、trace 定位到具体 LLM 调用、suspected_node 启发式、suspected_prompt 给出可直接编辑的 .md 路径。

### D8 · 上线节奏（现状）

| 里程碑 | 内容 | 状态 |
|--------|------|---|
| M1 · 骨架 | 新 graph/state + 3 Protocol + harness MVP | ✅（30 条 golden 全 PASS，历史退出门）|
| M2 · 子图实现 | 主干节点逐个实现 + golden 扩张 | ✅（PR #41；mock baseline 92.5% / 真 LLM 84.6%——**Qwen 口径，已被 ADR 0020 作废待重建**）|
| M3 · 工程联调闭环（[ADR 0016](./0016-m3-scope-engineering-loop-not-shadow.md) 重定义，非 shadow 双跑）| 真后端联调 + 真 LLM 评测 + 灰度工具链 | M3.1/M3.2 ✅；历史 #82-#87 已关闭，M3.3 是否满足退出门以当前 DeepSeek 评估与验收证据为准 |
| M4 · 金丝雀切换 | 按群组切流 + F4.1 shadow 第二意见 | 工具链就绪，未启动（[ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) / [0019](./0019-incident-severity-thresholds.md)）|

### D9 · M2 节点实现优先级（历史记录）

P0（swap.place_order / option intent+extract / close.place_close / ticker）→ P1（cancel / confirm / query 类）→ P2（image / excel / hand_to_share / query_status——除 query_status 已落地外仍是 backlog）。D9.2 退出门（ticker PASS ≥ 90% + 100% from_goats、三链路 ≥ 85%、P0 golden ≥ 80 条）已按当时口径通过。

## 实现偏离（2026-08-27 核查 [#139](https://github.com/GZTL-AI/aigc-langgraph/issues/139)，裁决另行处理）

| 偏离 | 现状 | 裁决 issue |
|---|---|---|
| **ticker "1 节点 = ReAct Agent 子图"名存实亡** | 主图从未 `add_node("ticker", ...)`；生产走 `ticker/resolver.py` 确定性流水线（tokenize → GOATS → 规则选优 → infer_code 兜底），`react_agent.py` 为死代码。节点计数 20 中的这 1 个是虚的 | [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154) |
| ~~AgentState 业务参数字段无类型契约~~ | ✅ **#160 落地（2026-08-27）**：新增 `app/graph/business_params.py` 状态级模型，15 个写入点全部经 `validated_*` 校验（extra=forbid 防字段名拼错，输出与历史 dict 逐字节一致）；运行时保持 dict（读取侧/checkpoint/eval 零改动）——这是 D6 意图在 M3.3 阶段的实现形态，全运行时对象化留 M4 后评估 |
| ~~D9.1 `--mock-ticker` 开关~~ | ✅ #160 裁决：**承诺撤销**——CI 回归由 pytest + mock LLM 承担（977 collected），harness golden 人工/评估触发；D9.1 该段转历史 |
| ~~harness 依赖面超纪律 3~~ | ✅ #160 裁决：**纪律放宽**为"harness 仅依赖三个稳定入口：`app.graph.main` / `app.config` / `app.llm.clients`"——现状即合规，新增依赖需回本表登记 |

关联的 checkpointer 未接线问题已由 [ADR 0021](./0021-text-confirm-replaces-interrupt.md) / [#153](https://github.com/GZTL-AI/aigc-langgraph/issues/153) 修复；数据库兼容边界见 [ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md)。

## 备选方案（历史论证，保留）

- **增量改造现有 `app/`**：节点划分不对齐 Dify、state 扁平铺、god class `otc_backend.py`（现已被 3 Protocol 取代）——节省的工作量被"边改边背债"抵消。
- **路 B 激进合并（19 → 5-6 节点）**：提示词 80% 重写、信息密度过载、shadow 无法 1:1 对比——为了重构而重构。
- **选保守路 A+**：逻辑层 1:1（仅合并 3 确认）+ 工程层全新做（Pydantic 契约 / @safe_node / 可 replay / harness），单位时间收益最大。

## 后果

### 积极（均已兑现）

- AI 工具自驱迭代：harness/LangFuse 输出可直接定位到 .md 文件
- bug 修复有回归基线：golden 已扩到 535 条
- 联调零阻塞：Protocol 切换实现即可
- 新意图有模板：`@safe_node` + Pydantic Output + .md 提示词 + golden case 四件套

### 消极与现状

| 后果 | 现状 |
|------|---|
| 重写期 `app/` 不可用 | 已过去（feature 分支已合 main）|
| `app/prompts/` 重构期可改写 | D5 处置表登记制运行中；M4 后恢复只读 |
| harness 运行成本 | 已可度量（token_tracker + llm_cost_report）；golden 分类分层跑 |

## Related

- [ADR 0000](./0000-migrate-from-dify-to-langgraph.md) · 迁移动机（四痛点）
- [ADR 0002](./0002-comprehensive-runtime-harness.md) · Harness 三阶段，本 ADR D7-D9 是其落地
- [ADR 0008](./0008-ticker-resolution-as-react-agent.md) · ticker ReAct 决策（现状偏离见上表 + [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154)）
- [ADR 0011](./0011-split-option-intent-and-extraction.md) · option 拆 **1 intent + 5 extract**（二次修订口径）
- [ADR 0012](./0012-restore-backend-http-for-securities-instrument.md) · 标的查询走后端 HTTP，D4 是其精确化（endpoint = `GET /admin-api/integration/securities-instrument/select`）
- [ADR 0014](./0014-langfuse-as-harness-backend.md) · LangFuse 后台（修订 D7）
- [ADR 0015](./0015-intent-route-rules-first-llm-fallback.md) · 一级路由（精确化 D6 的 intent_route）
- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · LLM 全量 DeepSeek-V4-pro（取代 ADR 0010 的选型口径）
- dify/yaml/主干工作流.yml（19 个 LLM 节点；已移出仓库，见 tag dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建））· `docs/api-contracts/java-backend.md` · `CONTEXT.md`
