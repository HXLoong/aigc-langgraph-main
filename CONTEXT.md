# otc-agent · Domain Context

场外衍生品 AI 指令助手（OTC Derivatives AI Instruction Agent）的领域语言、术语表和概念边界。
所有 issue / PRD / refactor 提案 / 测试命名都使用本文件定义的术语，不漂移到同义词。

## Language

### Engineering 术语

**Harness（评测台 / Harness Engineering）**：
一套把 "case → 跑 LangGraph → 比对预期 → 结构化输出失败原因 → 喂给 AI 工具改代码 → 再跑" 做成全自动闭环的工具链。包含 golden set、replay 工具、结构化 diff 报告、可被 Claude Code 单命令调用的 CLI。
_Avoid_: 混沌工程（Chaos Engineering，不同概念）、可观测性平台（trace 只是 harness 的副产品之一）、单元测试（粒度更粗，跑端到端）

**Golden case**：
一条 harness 输入：用户原话 + 期望输出（intent / product_type / 关键参数）。集合（golden set）是 harness 的回归基线。
_Avoid_: 测试用例（太泛）、fixture（语义不准）

**Shadow compare（双跑对照）**：
同一条 case 同时打到 Dify 和 LangGraph，diff 输出找差异。是 Dify→LangGraph 迁移期的验证工具，不是 harness 的核心功能。
_Avoid_: A/B test（语义不准，不涉及流量切分）

**节点（Node）**：
LangGraph 图中一个 `@safe_node` 装饰的 async 函数。在本项目语境下，节点和 Dify 的 LLM 节点 1:1 对齐（仅 3 个"确认 X"合并为 1）。
_Avoid_: step（太泛）、stage、handler

**LangFuse**：
本项目 Harness 的后台服务（self-hosted 部署在内网）。承载 trace / dataset / eval / annotation 四件套。**不**承载提示词的真理来源——`app/prompts/**/*.md` 是真理来源，LangFuse Prompts 仅作 staging 演练区。
_Avoid_: LangSmith（数据出境，已废止）、可观测性平台（窄了，LangFuse 还做评估和标注）

### 业务术语

**意图（Intent）**：
用户原话被识别后归类的二级动作，如 `place_order_request` / `cancel_order` / `query_order` / `close_position`。**一级路由是 product_type**（swap / option / close），二级才是 intent。
_Avoid_: action（与下单 algorithm type 的 "action" 字段冲突）、type（太泛）

**标的（Ticker / Instrument）**：
交易对象的唯一标识。在本项目内必须是经过 goats 库校验过的代码（`from_goats=True` 是绝对约束），不接受未经校验的字符串。
_Avoid_: stock（仅指股票）、symbol（不准确）、underlying（仅期权语境）

**Confirm 节点的 action 参数**：
合并版 `swap.confirm(action: "place" | "cancel" | "modify")`——同一个节点处理三种动作的二次确认，调用方传入 expected_action。
_Avoid_: 三个独立的"确认下单 / 确认撤单 / 确认改单"节点（已合并）

## Relationships

- 一份 **Golden case** 既被 **Harness** 用作回归基线，也可被 **Shadow compare** 用作双跑输入
- **Harness** 的失败报告会指向具体的 **节点（Node）**，让 AI 工具知道改哪里
- 一条用户原话先经一级路由到 **product_type**（swap / option / close），再由该子图内识别 **意图（Intent）**
- 任何 **标的** 出现在 LangGraph 输出前，必须经过 ticker 子图（ReAct Agent，4 个工具：tokenize / completeness / rank / infer_code）校验，最终输出 `from_goats=True`
- LangGraph 通过 4 个 **Protocol**（QuoteClient / OrderClient / PositionClient / TickerClient）调用 Java 后端业务 API，契约定义见 `docs/api-contracts/java-backend.md`

## Flagged ambiguities

- 用户原话写"混沌工程"，英文写"Harness Engineering"——这两个**不是同一个概念**。本项目语境下统一指 **Harness**，混沌工程不在本项目范畴。
