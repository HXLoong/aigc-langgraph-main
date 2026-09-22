# ADR 0006 · Human-in-the-Loop interrupt 边界：写操作 + 资金风险才拦

- 状态：**interrupt 机制部分已被 [ADR 0021](./0021-text-confirm-replaces-interrupt.md) 取代**（#153 裁决：文本二阶段确认为正式机制）；本文的"写 + 资金双轴"风险象限规则仍沿用
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony

## 决策（边界规则本体）

用 **"是否产生不可逆后端写操作 + 是否涉及资金/合约履行"双轴**决定哪些节点要进 `interrupt_before`：

| 类型 | 示例 | 是否 interrupt |
|---|---|---|
| 纯查询 | 持仓、订单状态、报价 | 否 |
| 写操作但低风险 | 修改订单备注等无金额影响字段 | 否 |
| 写操作 + 资金/合约 | `place_order` / `cancel_order` / `modify_order` / `place_close` | **是** |
| 已确认的二阶段意图 | `confirm_order` / `confirm_cancel` / `confirm_close` | 否（已确认过） |

## ⚠️ 落地现状（2026-08-27）：interrupt 机制整体缺失

核查（[#140](https://github.com/GZTL-AI/aigc-langgraph/issues/140)）确认本 ADR 的执行载体**一项都不存在**：

1. 主图 compile **无 `interrupt_before`**（全仓 `interrupt_before` / `interrupt(` 零命中）——表中"必拦"的四类写操作节点全部**直通后端**；
2. 生产图**不带 checkpointer**（`app/main.py` 以 `checkpointer=None` 编译；`app/checkpointer/factory.py` 的 AIOMySQLSaver 为未接线死代码）——即便加了 interrupt 也无法恢复；
3. 原设计的恢复入口 **`/v1/message/confirm` 端点不存在**（`app/api/routes.py` 仅有 `/v1/workflows/run`）。

**当前实际生效的唯一确认路径**：客户发文本"确认"→ 意图分类 → `confirm_*` 意图节点（swap/option/close 三子图均有此路由）。原设计中它是"按钮故障的天然兜底"，现状是**唯一路径**——业务上等价于"文本二阶段确认"，但从未作为决策记录。

**裁决结果**（[#153](https://github.com/GZTL-AI/aigc-langgraph/issues/153)，Tony 2026-08-27）：选 (b) + checkpointer 拆开接线——详见 [ADR 0021](./0021-text-confirm-replaces-interrupt.md)。新增节点仍须按上表 review 风险象限（规则本体有效），确认机制统一走文本二阶段（`confirm_*` 意图），不写 `interrupt_before`。

## 备选方案

- **全拦**：每个写动作都确认，摩擦过大（业务方反映"客户希望快速下单"）。
- **不拦**：下错单代价高，不可接受。
- **写 + 资金双轴（已选）**：摩擦只留给真正不可逆的动作。

## 后果（现状口径）

- "不可逆"是判断关键词：新增产品（如结构化产品）必须先标注每个意图是否"不可逆 + 资金"。
- 若走裁决选项 (a)：`interrupt_before` 列表是图结构一部分，增删拦截点影响已有 checkpoint 恢复语义，须配合 schema 演进策略；确认卡片回调链路需可用性监测 + 降级文案。
- ~~文档修正项：`.claude/rules/langgraph-patterns.md` 的 interrupt 示例用了不存在的节点名 `call_swap_api`~~ ✅ 已修正（2026-09-22 复核：该规则现写"不引入 interrupt 确认"，无 interrupt 示例）；`otc_agent_hitl_total{node}` 指标统计的是 **ticker 消歧卡片渲染次数**（`app/nodes/render.py`，非阻塞文本卡片），不是 interrupt 触发数，引用该指标的文档勿混淆。
