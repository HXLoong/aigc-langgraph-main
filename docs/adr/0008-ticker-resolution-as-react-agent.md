# ADR 0008 · 标的识别采用 ReAct Agent（历史存根）

- 状态：**已被 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md) 取代**（2026-09-20）
- 日期：2026-05-10
- 作者：图灵科技 + Tony

## 原决策

场外业务大量使用俗称与跨市场简称（"伦铜"= LME 铜期货，"腾讯"= 00700.HK），原决策在 LangGraph 内用 ReAct Agent + 工具循环完成"简称 → 证券代码"识别，并要求最终结果必须经后端证券池回查（`from_goats=True`）。

## 演进与取代

ReAct 形态从未接入生产，先后演进为"确定性编排 + LLM 兜底"与 LangGraph 原生子图；2026-09-20 整体移交 Java 后端。取代理由：

- 本地识别必然把"名称 → 代码"业务清单写进提示词与代码，违反"禁止硬编码业务数据字典"红线；
- 本地实现与 Java 标的工具是同一职责的两份实现，会漂移（[ADR 0012](./0012-restore-backend-http-for-securities-instrument.md) 已有先例）；
- 每次请求多 3 路 LLM 调用，而权威结果最终仍由后端决定。

原决策的业务动机（俗称、跨市场简称）依然成立，只是解决位置移到后端。演进细节见 [实施记录归档](../archive/history/adr-implementation-log-2026-09.md)。

## 仍有效的事实

- `TickerCandidate.from_goats` 仅作旧 checkpoint / HTTP 兼容字段；原文候选**不得**标记 `from_goats=True`。
- 本地生成的标的消歧卡片、零命中回复已全部退役。
