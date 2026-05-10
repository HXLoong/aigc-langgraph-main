# Human-in-the-Loop interrupt 边界：写操作 + 资金风险才拦

LangGraph 的 `interrupt_before` 可在指定节点前暂停图执行，等客户从企微确认卡片按钮回调后再恢复。我们用 **"是否产生不可逆后端写操作 + 是否涉及资金/合约履行"双轴** 决定哪些节点要进 `interrupt_before`：

| 类型 | 示例 | 是否 interrupt |
|---|---|---|
| 纯查询 | 持仓、订单状态、报价 | 否 |
| 写操作但低风险 | 修改订单备注等无金额影响字段 | 否 |
| 写操作 + 资金/合约 | `place_order` / `cancel_order` / `modify_order` / `place_close` | **是** |
| 已确认的二阶段意图 | `confirm_order` / `confirm_cancel` / `confirm_close` | 否（已确认过） |

新增节点时必须 review 是否落在"必拦"区间，相关约束写入 `.claude/rules/langgraph-patterns.md`。

## Considered Options

- **全拦**：每个写动作都确认，对客户摩擦过大（业务方反映"客户希望快速下单"）。
- **不拦**：风险不可接受，下错单代价高。
- **写 + 资金双轴（已选）**：把摩擦留给真正不可逆的动作，查询/低风险写不打断客户体验。

## Consequences

- "不可逆"是判断关键词。新增产品时（如未来加结构化产品），必须先标注每个意图是否"不可逆 + 资金"。
- 确认卡片回调路径（`/v1/message/confirm`）是 interrupt 恢复的唯一入口。如果企微按钮回调链路故障，所有"必拦"动作会卡住——需要监测这条链路的可用性，并设计降级文案（"按钮不可点时请回复'确认'文本"）。
- `interrupt_before` 列表在主图 compile 时声明，是图结构的一部分，新增/删除拦截点会影响已有 checkpoint 的恢复语义——必须配合 schema 演进策略。
- 客户主动发文本"确认"也能推进流程（走意图分类 → confirm_X），不依赖按钮——这给了按钮链路故障时的天然兜底，必须保留这条路径。
