# 路由歧义待决策项（E3.4 簇 B）

> 2026-05-12 · 阶段 3 真后端联调发现 · 业务方需 review

## 背景

E3.1 真后端跑 swap/confirm 类别 45 条 case，76%（34 条）失败聚类为"裸短语路由错"：

- "确认下单" / "确认改单" → 期望 `swap`，实际 `option`
- "确认撤单" → 期望 `swap`，实际 `option_close`

## 根因（代码现状）

`app/prompts/router/keywords.yaml` 优先级遍历：

| 优先级 | product_type | 含的关键词（节选）|
|---|---|---|
| 1 | option_close | "平仓" / "确认撤单" / "确认平仓" / "撤单" / ... |
| 2 | option | "期权" / "询价" / "**确认下单**" / "查询订单" / ... |
| 3 | swap | "互换" / "TRS" / "POV" / ... （**没有"确认下单"**）|

裸"确认下单"短语遍历优先级第 2 块（option）即命中 break，没机会落到 swap 块。这是 keywords.yaml 的固有结构 —— 不算 bug，是设计取舍。

## 三种处置选项（待业务方决策）

### 选项 A · 改路由规则

把"确认下单 / 确认改单 / 确认撤单"从 option / option_close 块移除，让 LLM 兜底（第 3 层）判定 product_type。

**风险**：LLM 在零上下文（无 quote_content）下也很难稳定判产品类型，可能仍会判错。

### 选项 B · 改 fixture 标注

把 fixture 中裸"确认下单"等 case 的 `expected.product_type` 从 swap 改为更宽容的判定（如允许 swap 或 option）—— 或者删除这种纯歧义 case。

**风险**：fixture 标注与生产实际客户语料的代表性可能脱节。

### 选项 C · 扩 swap 块 keywords（与 option 共存）

在 swap 块同样加"确认下单 / 确认改单 / 确认撤单"，并调整匹配策略（如改成"首匹配产品 = 上下文相关"，需要 keywords.yaml 数据结构重设计）。

**风险**：keywords.yaml 现行优先级 break 语义被破坏，整个路由层需要重写。

## 需业务方提供的信息

请业务方 / PM 提供以下数据，便于决策：

1. **真实客户语料中裸"确认下单"短语的频率**：
   - 是否大多数客户都会带订单号（如"确认下单 H-XXX"）？
   - 还是常出现无上下文的裸短语（"确认下单"）？

2. **歧义场景的合理处置**：
   - 如果客户在 swap 群说"确认下单"，期望系统识别为 swap.confirm 还是要求用户补"互换"？
   - 群上下文（roomId）能否作为 fallback 信号？

3. **fixture 标注的来源**：
   - 这些 fixture case 是从真实客户日志抽样还是构造的极端测试？
   - 若是构造的，是否应该改成"swap 确认下单"等更明确形式？

## 工程侧已完成的可观测性补强

`intent_route` 节点的 trace decision 现在记录命中的具体 keyword：

```
旧: rule:keyword→option
新: rule:keyword[kw:确认下单]→option
```

便于 E3.4 错例追溯：业务方看 trace 即可知道"为什么路由到 option"。

## 关联

- Issue #82 E3.1 · 真后端 PASS rate
- Issue #85 E3.4 · 错例聚类
- `docs/m3-e3-real-backend-sample.md` · 三簇分析报告
- `app/prompts/router/keywords.yaml` · 关键词优先级表
