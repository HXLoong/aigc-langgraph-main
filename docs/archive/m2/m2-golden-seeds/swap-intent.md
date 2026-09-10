# Golden 种子收集 · swap.intent

> grill-with-docs 2026-05-10 第 4 决策落地 · 业务方填空，工程师转 jsonl

## 节点描述

**互换二级意图分类（在 product_type=swap 内部）。**

| 字段 | 值 |
|---|---|
| 节点 | `swap.intent` |
| product_type | `swap` |
| 合法 intent 枚举 | `place_order_request`, `cancel_order_request`, `confirm_order`, `confirm_cancel_order`, `confirm_modify_order`, `query_order_status`, `unknown_intent` |

## 填空指南

- 每条 case 写一段自然语言（用户在企微群里可能说的原话）
- 只标 `expected.product_type` + `expected.intent`，参数细节不用标
- 至少填 6 条，建议覆盖：标准表达 / 缩写 / 错别字 / 多目标 / 边界场景
- 引用消息的 case，请把上一条客服消息填到 `quote_content`

## 示例输入（启发用，不是强制 case）

- 互换下单 招商银行 1000 股
- 撤 H-20260304-0000001
- swap确认下单 H-20260304-ABCD12345678
- 查一下 H-20260304-0000001 的状态

## Case 槽位（按编号填）

### Case 1

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 2

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 3

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 4

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 5

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 6

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 7

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

### Case 8

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: swap
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

