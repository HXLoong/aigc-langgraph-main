# Golden 种子收集 · ticker.react_agent

> grill-with-docs 2026-05-10 第 4 决策落地 · 业务方填空，工程师转 jsonl

## 节点描述

**标的识别 ReAct Agent。输入用户原话，输出 from_goats=True 的标的代码列表。**

| 字段 | 值 |
|---|---|
| 节点 | `ticker.react_agent` |
| product_type | `ticker` |
| 合法 intent 枚举 | (无 intent 字段，输出 list[TickerCandidate]) |

## 填空指南

- 每条 case 写一段自然语言（用户在企微群里可能说的原话）
- 只标 `expected.product_type` + `expected.intent`，参数细节不用标
- 至少填 6 条，建议覆盖：标准表达 / 缩写 / 错别字 / 多目标 / 边界场景
- 引用消息的 case，请把上一条客服消息填到 `quote_content`

## 示例输入（启发用，不是强制 case）

- 做一笔 00700.HK 的 TRS
- 腾讯
- 伦铜下月合约
- 买 50ETF 一些
- 纳指

## Case 槽位（按编号填）

### Case 1

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 2

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 3

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 4

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 5

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 6

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 7

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 8

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: ticker
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

