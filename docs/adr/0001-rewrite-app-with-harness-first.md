# ADR 0001 · 推倒重写 `app/`，按 Harness-first 范式落实 LangGraph 替换 Dify

## 状态

- 状态：已采纳
- 日期：2026-05-10
- 关系：D5 与「备选方案」的评估轴由 [ADR 0031](./0031-single-model-request-per-message.md) 修订；标的职责见 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)；协议演进见 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D7；评测门见 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3
- 作者：图灵科技 + Tony

## 背景

重写前的 `app/` 是自动生成的迁移骨架：节点划分与真实 Dify 工作流不一一对应、对 Java 后端的契约不明确、缺少可独立回放的节点接口、测试是"先写代码再补"。决定推倒重写，按 **Harness-first**（先有评测与契约，再有实现）推进。

## 决策

### D1 · 重写边界

重写 State、主图、子图、节点、工具层、API 与测试；新增与 `app/` 解耦的 `harness/` 评测台。

### D2 · 工具层按 Java 真实 endpoint 拆分 Protocol

后端调用清单的唯一维护处为 [Java / GOATS 出站 API 清单](../api-contracts/java-backend.md#langgraph-出站后端-api-清单)，列出完整 HTTP 方法、路径、客户端和用途，区分业务调用与本地验收 / 健康检查。调用方依赖 OptionClient、SwapClient、MessageClient、GoatsAgentClient 的 Protocol。

`TickerClient`（`app/tools/ticker_client.py`）保留用于授权交易对手列表查询，不提供 LangGraph 标的识别职责。`GET /admin-api/integration/securities-instrument/select`（简称 `/securities-instrument/select`）禁止被任何 LangGraph 本地流程调用，包括业务链、测试、验收脚本和探针；标的识别由 Java 内部工作流完成（ADR 0025）。

入参出参匹配 Java DTO 字段名，保留结构类型约束；业务归一化与数字校验按 ADR 0027 交由 Java。节点不直接创建 `httpx.AsyncClient` 调后端，统一经 Client Protocol 与连接池。

### D3 · 对 Java 暴露 Dify 兼容协议

`POST /v1/workflows/run` 兼容 Dify Workflow Run API（blocking 模式）。切换或回滚只需改 Java 侧 `agentUrl`；原生协议规划见 ADR 0024 D7（暂缓）。

### D4 · 标的识别归 Java 后端

LangGraph 提取标的原始表达或用户对引用候选的明确选择，通过业务接口提交；Java 调用对应的标的识别工作流并完成业务校验（[ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)）。

### D5 · 节点策略：一次解析，确定性处理分层

每次工具调用全链路最多一次模型请求，产品、意图与必要候选共用一次解析结果（[ADR 0031](./0031-single-model-request-per-message.md)，目标规范已采纳，代码待重构）。产品子图、结构与来源检查、引用选择及后端执行保持独立职责，只做订单号提取的步骤继续由代码处理。

用 PromptSpec、按产品与意图组织的输出契约和数据集回归控制联合解析复杂度；业务节点数量不作为模型请求次数的替代指标。

### D6 · 目录结构与 AgentState

- 一节点一文件、测试按意图组对应；`AgentState` 按业务对象聚合（`app/graph/state.py`），harness 按业务对象比对，新增意图只加字段不破坏结构。
- 业务参数字段由 `app/graph/business_params.py` 状态级模型校验（`extra=forbid` 防字段名拼错）。
- harness 与 `app/` 解耦，只经 HTTP 入口驱动（[ADR 0002](./0002-comprehensive-runtime-harness.md)）。

### D7 · 失败报告格式

机器读 = LangFuse Trace API；人读 = LangFuse UI；CI 离线 = 本地 JSON（`.harness-runs/`，含字段级 diff 与逐节点 trace）。设计要点：字段级 diff 比文本 diff 更快定位，trace 定位到具体 LLM 调用与提示词文件。

## 备选方案

> 评估轴已按 [ADR 0031](./0031-single-model-request-per-message.md) 重述（它修订了 D5）：决定划分的不是节点数量，而是**每次工具调用实际发起的模型请求次数**；合并模型节点本身不是收益，用输出契约与回归数据控制合并后的复杂度才是。

- **增量改造现有 `app/`**：节点划分不对齐、状态扁平、后端调用集中在一个大类中，"边改边背债"抵消收益。
- **按节点数激进合并（约 19 → 5-6 节点）**：以"少写节点"为目标，提示词大面积重写、信息密度过载、无法与原流程逐节点对比。0031 之后这条轴已被否——业务节点数量不作为模型请求次数的替代指标，且不要求把所有产品合成一套大提示词。
- **保守路线 A+（已选）**：**确定性**分层保持逻辑层 1:1（结构与来源检查、引用选择、后端执行各守其责）+ 工程层全新（Pydantic 契约 / `@safe_node` / 可回放 / harness），单位时间收益最大。
- **模型解析层收敛（0031 现行方案，已采纳、代码待重构）**：同一次调用最多一次请求且零重试，因此产品分类、意图识别、候选选择与参数提取合并为**互斥的四选一联合解析器**（互换 / 期权 / 平仓 / 跨产品），产品不明确时由跨产品解析器在同一次请求内一并判断；禁止用合并函数、逐订单 / 逐附件处理或 Agent 循环规避额度。合并后同步迁移 PromptSpec、harness 注册、节点 fixture 与流程文档。

## 后果（均已兑现）

- 评测与 LangFuse 输出可直接定位到提示词文件，AI 工具可自驱迭代。
- 缺陷修复有数据集回归基线；联调通过切换 Protocol 实现即可完成。
- 新意图有固定模板：`@safe_node` + Pydantic 输出模型 + `.md` 提示词 + golden case。
