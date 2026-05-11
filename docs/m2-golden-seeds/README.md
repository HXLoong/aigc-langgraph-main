# M2 Golden 种子收集索引

> grill-with-docs 2026-05-10 第 4 决策落地 · 业务方填空

共 **19** 个 M2 节点等待业务方种子。每个节点至少 6-8 条，
总目标 ≥ 80 条以满足 P0 退出门（ADR 0001 D9.2）。

## 节点列表

| 节点 | product_type | 模板文件 |
|---|---|---|
| `close.cancel_close` | `option_close` | [close-cancel_close.md](close-cancel_close.md) |
| `close.confirm_cancel` | `option_close` | [close-confirm_cancel.md](close-confirm_cancel.md) |
| `close.confirm_close` | `option_close` | [close-confirm_close.md](close-confirm_close.md) |
| `close.holding_query` | `option_close` | [close-holding_query.md](close-holding_query.md) |
| `close.intent` | `option_close` | [close-intent.md](close-intent.md) |
| `close.place_close` | `option_close` | [close-place_close.md](close-place_close.md) |
| `close.query_status` | `option_close` | [close-query_status.md](close-query_status.md) |
| `option.extract_cancel` | `option` | [option-extract_cancel.md](option-extract_cancel.md) |
| `option.extract_confirm` | `option` | [option-extract_confirm.md](option-extract_confirm.md) |
| `option.extract_inquiry` | `option` | [option-extract_inquiry.md](option-extract_inquiry.md) |
| `option.extract_place_or_modify` | `option` | [option-extract_place_or_modify.md](option-extract_place_or_modify.md) |
| `option.extract_query` | `option` | [option-extract_query.md](option-extract_query.md) |
| `option.intent` | `option` | [option-intent.md](option-intent.md) |
| `swap.cancel` | `swap` | [swap-cancel.md](swap-cancel.md) |
| `swap.confirm` | `swap` | [swap-confirm.md](swap-confirm.md) |
| `swap.intent` | `swap` | [swap-intent.md](swap-intent.md) |
| `swap.place_order` | `swap` | [swap-place_order.md](swap-place_order.md) |
| `swap.query_order` | `swap` | [swap-query_order.md](swap-query_order.md) |
| `ticker.react_agent` | `ticker` | [ticker-react_agent.md](ticker-react_agent.md) |

## 填空指南

- 每个文件含 8 个 case 槽位，至少填 6 条
- 只标 `expected.product_type` + `expected.intent`，参数细节不标
- 写完后由工程师转 jsonl 合入 `tests/fixtures/golden.jsonl`
- 所有种子标 `source: business_seed`（B 桶 PASS 阈值 ≥ 90%）
