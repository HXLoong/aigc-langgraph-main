# ADR 0001 · 推倒重写 `app/`，按 Harness-first 范式落实 LangGraph 替换 Dify

- 状态：已采纳（重写已完成）
- 日期：2026-05-10
- 关系：D4 标的职责被 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md) 反转；D3 协议演进见 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D7；原上线节奏与优先级段随 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) 退役
- 作者：图灵科技 + Tony

## 背景

2026-05 时 `app/` 是早期自动生成的迁移骨架：节点划分与真实 Dify 工作流不一一对应、对 Java 后端的契约不明确、缺少可独立回放的节点接口、测试是"先写代码再补"。决定推倒重写，按 **Harness-first**（先有评测与契约，再有实现）推进。

## 决策

### D1 · 重写边界

保留提示词资产与 checkpointer 工厂；重写 State、主图、子图、节点、工具层、API 与测试；新增与 `app/` 解耦的 `harness/` 评测台。

### D2 · 工具层按 Java 真实 endpoint 拆分 Protocol

| Protocol | 覆盖范围 | 后端 endpoint |
|---|---|---|
| `OptionClient`（`app/tools/option_client.py`） | 期权全流程 | `POST /financial-orders/operate` 等 |
| `SwapClient`（`app/tools/swap_client.py`） | 互换全流程 | `POST /swap-order/operate` 等 |
| `TickerClient`（`app/tools/ticker_client.py`） | 历史标的查询（现已无业务调用方，见 ADR 0025） | `GET /securities-instrument/select` |

纪律：入参出参用 Pydantic 模型并严格匹配 Java DTO 字段名；枚举用 `Literal` 约束；金额用 `Decimal`；调用方只依赖 Protocol；业务代码禁止直接 `httpx.AsyncClient` 调后端。契约详见 `docs/api-contracts/java-backend.md`。

### D3 · 对 Java 暴露 Dify 兼容协议

`POST /v1/workflows/run` 兼容 Dify Workflow Run API（blocking 模式）。迁移期协议一致，回滚只需改 Java 侧 `agentUrl`。原生协议的规划见 ADR 0024 D7（当前暂缓）。

### D4 · ~~标的查询职责归 LangGraph~~

2026-09-20 反转：标的识别整体移交 Java 后端，LangGraph 只提取原文（[ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)）。

### D5 · 节点策略：保守路线 A+

逻辑层与原 Dify 工作流基本 1:1，仅做定向重构：互换 3 个"确认 X"节点合并为 1 个统一确认；期权巨型意图 + 抽取节点拆分为"1 意图 + 分意图抽取"（[ADR 0011](./0011-split-option-intent-and-extraction.md)）；只做订单号提取的节点改为确定性代码（去 LLM 化）。

不走激进合并的理由：用户最痛的问题（标的不准、参数错、缺少评估）分别靠后端权威识别、Pydantic 契约和 harness 解决，不靠节点合并；激进合并会让提示词信息密度过载、diff 颗粒度变粗。

逐批的合并 / 拆分 / 瘦身 / 去 LLM 化处置记录见 [实施记录归档](../archive/history/adr-implementation-log-2026-09.md)。

### D6 · 目录结构与 AgentState

- 一节点一文件、测试按意图组对应；`AgentState` 按业务对象聚合（`app/graph/state.py`），harness 按业务对象比对，新增意图只加字段不破坏结构。
- 业务参数字段由 `app/graph/business_params.py` 状态级模型校验（`extra=forbid` 防字段名拼错）。
- harness 与 `app/` 解耦，只经 HTTP 入口驱动（[ADR 0002](./0002-comprehensive-runtime-harness.md)）。

### D7 · 失败报告格式

机器读 = LangFuse Trace API；人读 = LangFuse UI；CI 离线 = 本地 JSON（`.harness-runs/`，含字段级 diff 与逐节点 trace）。设计要点：字段级 diff 比文本 diff 更快定位，trace 定位到具体 LLM 调用与提示词文件。

## 备选方案

- **增量改造现有 `app/`**：节点划分不对齐、状态扁平、后端调用集中在一个大类中，"边改边背债"抵消收益。
- **激进合并（约 19 → 5-6 节点）**：提示词大面积重写、信息密度过载、无法与原流程逐节点对比。
- **保守路线 A+（已选）**：逻辑层 1:1 + 工程层全新（Pydantic 契约 / `@safe_node` / 可回放 / harness），单位时间收益最大。

## 后果（均已兑现）

- 评测与 LangFuse 输出可直接定位到提示词文件，AI 工具可自驱迭代。
- 缺陷修复有数据集回归基线；联调通过切换 Protocol 实现即可完成。
- 新意图有固定模板：`@safe_node` + Pydantic 输出模型 + `.md` 提示词 + golden case。
