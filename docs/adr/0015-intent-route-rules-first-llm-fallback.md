# ADR 0015 · 一级路由：规则前置 + LLM 兜底

- 状态：已采纳
- 日期：2026-08-28
- 关系：入口层由 [ADR 0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) 前置；新增产品时遵循 [ADR 0007](./0007-subgraph-vs-intent-scope-rule.md)
- 作者：图灵科技 + Tony

## 背景

主图需要把客户原话路由到一级产品类目：互换（swap）/ 期权（option）/ 期权平仓（option_close）/ 未知（unknown）。事实前提：订单号前缀是业务硬约定（"订单号优先于关键词"）；强信号消息占比高；口语化、有歧义的消息必须靠 LLM。

## 决策

规则能确定的不调用 LLM，LLM 只处理真正的歧义：

1. **规则层**（`app/nodes/route_rules.py`，确定性，< 1ms）：订单号正则（如 `H-` 互换、`Q-` 期权、`CO-` 平仓）、引用卡片内容、口语化平仓表达、互换下单特征、平仓查询关键词与关键词计数，以及附件分类（全图片 / 全 Excel → 互换多模态）。含多轮语境增强：引用内容带期权特征或引用持仓卡时，优先归期权 / 期权平仓，避免被互换特征误判。
2. **LLM 兜底**（`app/nodes/intent_route.py`，提示词 `app/prompts/router/unknown_intent.md`）：规则未命中时调用，输入包含原文与引用内容，结构化输出一级类目。
3. **多轮粘性**：规则与 LLM 均判 unknown，且会话上一轮有明确产品类目时继承之（如裸发"确认下单"）。
4. **unknown 兜底**：仍无法判定 → 统一引导回复，不进入子图。

每次判定在 trace 中记录来源：`rule→<类目>` / `llm→<类目>` / `sticky→<类目>`，便于统计规则覆盖率与追溯错例。

## 备选方案

- **纯 LLM 分类**：强信号消息白增 200-500ms；硬约定写进提示词仍有违反概率；结果抖动。
- **纯规则**：处理不了口语化与歧义，unknown 比例过高。
- **规则前置 + LLM 兜底（已选）**：硬约定 100% 一致，LLM 只处理真歧义。

## 后果

- 大部分流量省一次 LLM 调用，成本与延迟双优。
- 新增产品需同步规则层、兜底提示词、标签映射与数据集；订单号前缀变更须走 ADR 并回归评估。
- 规则层会随错例分析持续生长，新增规则必须在 trace 来源中可辨识，并有回归用例（`tests/nodes/test_route_rules_context.py`、`tests/nodes/test_intent_route_sticky.py`）。
