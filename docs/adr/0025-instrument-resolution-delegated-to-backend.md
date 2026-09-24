# ADR 0025 · 标的识别职责移交 Java 后端：LangGraph 只提取原文候选

- 状态：已采纳（追认：2026-09-20 落地于 commit `2f9ce65`，2026-09-22 补记）
- 日期：2026-09-20
- 关系：取代 [ADR 0008](./0008-ticker-resolution-as-react-agent.md)；修订 [ADR 0001](./0001-rewrite-app-with-harness-first.md) D4、[ADR 0012](./0012-restore-backend-http-for-securities-instrument.md)、[ADR 0023](./0023-prompt-as-code-langgraph.md)、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D2 / D3
- 执行说明：[docs/backend-instrument-boundary.md](../backend-instrument-boundary.md)
- 作者：图灵科技 + Tony

## 背景

标的识别在本仓经历三种形态（ReAct Agent → 确定性编排 + 后端二次校验 → LangGraph 原生子图），共同前提是"LangGraph 本地产出证券代码"。这一前提带来三类持续成本：

1. **业务清单长进代码**："名称 → 代码"事实清单与数百行分词规则写在提示词里，违反"禁止硬编码业务数据字典"红线，并随新 ETF / 指数发行持续过期。
2. **双实现漂移**：本地推断 + 排序与 Java 标的工具是同一职责的两份实现（ADR 0012 已有先例）。
3. **成本与幻觉**：每次下单 / 询价多 3 路 LLM 调用；本地校验失败时生成"零命中 / 消歧卡"，会拦下后端本可识别的请求。

2026-09-20 用户指定的主工作流职责边界把标的工具调用放在 Java 侧。

## 决策

### D1 · LangGraph 只提取原文与用户选择

- 保留用户的证券表达原文（代码或名称）与对引用候选的选择（序号 / 直接换标的），交给业务接口；**不补代码、不计算近月合约、不查证券池、不做本地预检、不因本地未匹配而拦截**。
- 来源记为"用户原文"或"引用"，**不得标记 `from_goats=True`**；该字段仅作旧数据兼容。

### D2 · 数据流

```
互换文本      → 原文候选 → 证据校验 / 归一化 → 对手或引用标的选择 → POST /swap-order/operate
图片 / Excel  → 转写 / 逐行候选 → 证据校验 / 归一化 → POST /swap-order/operate
普通期权询价  → 原文候选 → 证据校验 / 归一化 → POST /financial-orders/operate
```

Java 负责精确匹配、标的工具调用、多候选处理、权限与市场校验；业务回复沿用后端回执契约（[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) D3）。

### D3 · 兼容边界

- Java DTO 与 HTTP 路径不变：`placeOrderWindCode` / `stockCode` 可承载原始名称或代码。
- HTTP 输出 `tickers` 保持空列表兼容字段，**不能解释为后端未匹配**；本地不再生成证券零命中回复或消歧卡。
- 本地 ticker 子图、提示词与测试已删除；`app/tools/ticker_client.py` 为遗留客户端，已无业务调用方，去留待定。

### D4 · 验证口径

业务回归检查**传给后端的原始表达**与**后端实际回复**；统一验收只使用显式 `tests/fixtures/categories/`。

## 备选方案

- **保留本地识别 + 后端二次校验**：准确性最终仍由后端决定，本地只是会漂移的副本，且业务清单必然进代码。
- **本地只做精确匹配、不做 LLM 推断**：仍需维护匹配规则与零命中语义，且会误伤后端能识别的表达。
- **原文透传 + 后端权威识别（已选）**：单一真源，代码与业务清单解耦。

## 后果

- 正面：标的准确性归后端单一真源；每请求少 3 路 LLM 调用，幻觉错标的面归零；提示词不再承载证券事实清单。
- 负面：本地评测无法独立判定"标的是否正确"，只能断言原文透传与后端卡片；排错必经后端标的工具日志。
- 未决：`tickers` 兼容字段何时从外部协议移除；`ticker_client.py` 去留。
