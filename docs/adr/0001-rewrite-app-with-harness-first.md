# ADR 0001 · 推倒重写 `app/`，按 Harness-first 范式落实 LangGraph 替换 Dify

- 状态：已采纳（重写已完成）
- 日期：2026-05-10
- 关系：D5 由 [ADR 0031](./0031-single-model-request-per-message.md) 修订；标的职责见 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)；协议演进见 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D7；评测门见 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3
- 作者：图灵科技 + Tony

## 背景

重写前的 `app/` 是自动生成的迁移骨架：节点划分与真实 Dify 工作流不一一对应、对 Java 后端的契约不明确、缺少可独立回放的节点接口、测试是"先写代码再补"。决定推倒重写，按 **Harness-first**（先有评测与契约，再有实现）推进。

## 决策

### D1 · 重写边界

保留提示词资产与 checkpointer 工厂；重写 State、主图、子图、节点、工具层、API 与测试；新增与 `app/` 解耦的 `harness/` 评测台。

### D2 · 工具层按 Java 真实 endpoint 拆分 Protocol

| Protocol | 覆盖范围 | 后端 endpoint |
|---|---|---|
| `OptionClient`（`app/tools/option_client.py`） | 期权全流程 | `POST /financial-orders/operate` 等 |
| `SwapClient`（`app/tools/swap_client.py`） | 互换全流程 | `POST /swap-order/operate` 等 |
| `TickerClient`（`app/tools/ticker_client.py`） | 授权交易对手列表（仅本地验收脚本使用，交易链路不调用，见 ADR 0025） | `GET /securities-instrument/select` 等 |

纪律：入参出参用 Pydantic 模型并严格匹配 Java DTO 字段名；枚举用 `Literal` 约束；金额用 `Decimal`；调用方只依赖 Protocol；业务代码禁止直接 `httpx.AsyncClient` 调后端。契约详见 `docs/api-contracts/java-backend.md`。

### D3 · 对 Java 暴露 Dify 兼容协议

`POST /v1/workflows/run` 兼容 Dify Workflow Run API（blocking 模式）。切换或回滚只需改 Java 侧 `agentUrl`；原生协议规划见 ADR 0024 D7（暂缓）。

### D4 · 标的识别归 Java 后端

LangGraph 只提取证券表达原文，识别与校验由 Java 调标的工具完成（[ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)）。

### D5 · 节点策略：一次解析，确定性处理分层

每条消息全链路最多一次模型请求，产品、意图与必要候选共用一次解析结果（[ADR 0031](./0031-single-model-request-per-message.md)，目标规范已采纳，代码待重构）。产品子图、字段证据校验、归一化、确认及后端执行保持独立职责，只做订单号提取的步骤继续由代码处理。

用 PromptSpec、按产品与意图组织的输出契约和数据集回归控制联合解析复杂度；业务节点数量不作为模型请求次数的替代指标。

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
