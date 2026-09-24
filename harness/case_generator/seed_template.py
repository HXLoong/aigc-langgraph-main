"""业务方 golden 种子收集模板生成器（grill-with-docs 2026-05-10 第 4 决策）。

为 NODE_REGISTRY 中的每个节点生成一份 markdown 模板，业务方填空填出 6-8 条种子 case。
业务方填完后由工具转 jsonl 合入 `tests/fixtures/biz/`。

模板填空原则：
- 只标 product_type + intent（路由层），不标参数细节
- 参数级 expected 由 harness 跑出 actual 后业务方再 review

生成方式：
    from harness.case_generator import render_seed_template
    md = render_seed_template("swap.place_order")
    # 写到 <out-dir>/swap-place-order.md（默认 tmp/case_generator/seeds/）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeSeedSpec:
    """单节点的种子收集规约。"""

    node_name: str
    product_type: str  # "swap" / "option" / "option_close"
    intent_values: list[str]  # 该节点对应的合法 intent 枚举
    description: str  # 中文描述
    sample_inputs: list[str] = field(default_factory=list)  # 示例输入（启发业务方）


# ============================================================
# 各节点的种子规约
# ============================================================

#: 节点 → 种子规约（按 ADR 0001 D9 P0/P1/P2 优先级排序）
NODE_REGISTRY: dict[str, NodeSeedSpec] = {
    # ---- swap 子图（10 节点，P0/P1/P2）----
    "swap.intent": NodeSeedSpec(
        node_name="swap.intent",
        product_type="swap",
        intent_values=[
            "place_order_request",
            "cancel_order_request",
            "confirm_order",
            "confirm_cancel_order",
            "confirm_modify_order",
            "query_order_status",
            "unknown_intent",
        ],
        description="互换二级意图分类（在 product_type=swap 内部）。",
        sample_inputs=[
            "互换下单 招商银行 1000 股",
            "撤 H-20260304-0000001",
            "swap确认下单 H-20260304-ABCD12345678",
            "查一下 H-20260304-0000001 的状态",
        ],
    ),
    "swap.place_order": NodeSeedSpec(
        node_name="swap.place_order",
        product_type="swap",
        intent_values=["place_order_request"],
        description="互换下单/改单参数提取（共用 schema，靠 orderId 区分）。",
        sample_inputs=[
            "互换下单 帮我买入1000股腾讯控股，市价单",
            "做一笔招商银行的 TRS，买 1000 手，市价",
            "互换下单 同时买入贵州茅台、腾讯各 100 股",
            "改单 H-20260304-0001 价格改 150",
        ],
    ),
    "swap.confirm": NodeSeedSpec(
        node_name="swap.confirm",
        product_type="swap",
        intent_values=["confirm_order", "confirm_cancel_order", "confirm_modify_order"],
        description="互换确认（合并 3 个原 confirm 节点，靠 expected_action 区分）。",
        sample_inputs=[
            "互换 确认下单 H-20260304-ABCD12345678",
            "swap确认撤单 H-20260304-0001",
            "swap确认修改订单 H-20260304-0001",
        ],
    ),
    "swap.cancel": NodeSeedSpec(
        node_name="swap.cancel",
        product_type="swap",
        intent_values=["cancel_order_request"],
        description="互换撤单参数提取。",
        sample_inputs=[
            "撤 H-20260304-0000001",
            "互换撤单 H-20260304-ABCD12345678",
        ],
    ),
    "swap.query_order": NodeSeedSpec(
        node_name="swap.query_order",
        product_type="swap",
        intent_values=["query_order_status"],
        description="互换查询订单状态。",
        sample_inputs=[
            "TRS 查一下 H-20260304-0001 的状态",
            "互换 查询订单 H-20260304-0002",
        ],
    ),
    # ---- option 子图（6 节点，5 extract，P0）----
    "option.intent": NodeSeedSpec(
        node_name="option.intent",
        product_type="option",
        intent_values=[
            "new_inquiry",
            "place_order_from_quote",
            "confirm_order",
            "cancel_order_request",
            "request_cancel_order",
            "confirm_cancel_order",
            "query_order_status",
            "unknown_intent",
        ],
        description="期权二级意图分类（DSL v2:7 意图 + unknown,不含 close_order_*）。",
        sample_inputs=[
            "期权询价 腾讯控股 欧式看涨 行权价500 1个月",
            "确认第二笔",
            "期权撤单 Q-20260304-0000000001",
        ],
    ),
    "option.extract_inquiry": NodeSeedSpec(
        node_name="option.extract_inquiry",
        product_type="option",
        intent_values=["new_inquiry"],
        description="期权询价参数提取（new_inquiry）。",
        sample_inputs=[
            "参与型看涨 腾讯控股 1个月",
            "雪球询价 腾讯控股",
            "帮我询价茅台 3 个月雪球 名义 1000w",
        ],
    ),
    "option.extract_place": NodeSeedSpec(
        node_name="option.extract_place",
        product_type="option",
        intent_values=["place_order_from_quote"],
        description="期权下单参数（DSL v2 拆分：报价引用场景下单，含改单归类）。",
        sample_inputs=[
            "期权下单 茅台 欧式看涨 行权价 1800 期限 1M 名义 500万",
            "改单 Q-20260304-0000000001 行权价改 1850",
        ],
    ),
    "option.extract_cancel_place": NodeSeedSpec(
        node_name="option.extract_cancel_place",
        product_type="option",
        intent_values=["cancel_order_request"],
        description="期权取消下单参数提取（DSL v2 拆分）。",
        sample_inputs=[
            "不下了，取消这笔期权",
            "算了先不要下单",
        ],
    ),
    "option.extract_cancel": NodeSeedSpec(
        node_name="option.extract_cancel",
        product_type="option",
        intent_values=["request_cancel_order"],
        description="期权撤单请求参数提取（DSL v2：仅 request_cancel_order）。",
        sample_inputs=[
            "期权撤单 Q-20260304-0000000001",
            "撤销期权订单 Q-20260304-0000000002",
        ],
    ),
    "option.extract_confirm_place": NodeSeedSpec(
        node_name="option.extract_confirm_place",
        product_type="option",
        intent_values=["confirm_order"],
        description="期权确认下单参数提取（DSL v2 拆分）。",
        sample_inputs=[
            "确认第二笔",
            "期权 确认下单 Q-20260304-0000000001",
        ],
    ),
    "option.extract_confirm_cancel": NodeSeedSpec(
        node_name="option.extract_confirm_cancel",
        product_type="option",
        intent_values=["confirm_cancel_order"],
        description="期权确认撤单参数提取（DSL v2 拆分）。",
        sample_inputs=[
            "确认期权撤单 Q-20260304-0000000001",
        ],
    ),
    "option.extract_query": NodeSeedSpec(
        node_name="option.extract_query",
        product_type="option",
        intent_values=["query_order_status"],
        description="期权查询订单状态参数提取。",
        sample_inputs=[
            "查询期权订单 OPT-20260304-0001 状态",
            "OPT-20260304-0001 现在怎么样了",
        ],
    ),
    # ---- option_close 子图（7 节点，P0/P1）----
    "close.intent": NodeSeedSpec(
        node_name="close.intent",
        product_type="option_close",
        intent_values=[
            "close_order_query",
            "close_order_request",
            "close_order_confirm",
            "close_order_cancel_request",
            "close_order_cancel_confirm",
            "close_order_order_query",
        ],
        description="期权平仓二级意图分类。",
        sample_inputs=[
            "我有哪些期权持仓",
            "平 CO-20260304-4FE9C941 全部",
            "确认平仓 CO-20260304-ABCD1234",
        ],
    ),
    "close.holding_query": NodeSeedSpec(
        node_name="close.holding_query",
        product_type="option_close",
        intent_values=["close_order_query"],
        description="持仓查询（前置查询）。",
        sample_inputs=[
            "我有哪些期权持仓",
            "查一下我现在的持仓",
        ],
    ),
    "close.place_close": NodeSeedSpec(
        node_name="close.place_close",
        product_type="option_close",
        intent_values=["close_order_request"],
        description="平仓下单参数提取。",
        sample_inputs=[
            "平 CO-20260304-4FE9C941 全部",
            "帮我平仓 CO-20260304-ABCD1234",
            "平 茅台 一半",
        ],
    ),
    "close.confirm_close": NodeSeedSpec(
        node_name="close.confirm_close",
        product_type="option_close",
        intent_values=["close_order_confirm"],
        description="确认平仓参数提取。",
        sample_inputs=[
            "确认平仓 CO-20260304-ABCD1234",
            "确认 CO-20260304-0001",
        ],
    ),
    "close.cancel_close": NodeSeedSpec(
        node_name="close.cancel_close",
        product_type="option_close",
        intent_values=["close_order_cancel_request"],
        description="平仓撤单参数提取（撤销已下的平仓单）。",
        sample_inputs=[
            "撤销平仓单 CO-20260304-ABCD1234",
            "取消平仓 CO-20260304-0001",
        ],
    ),
    "close.confirm_cancel": NodeSeedSpec(
        node_name="close.confirm_cancel",
        product_type="option_close",
        intent_values=["close_order_cancel_confirm"],
        description="确认撤销平仓参数提取。",
        sample_inputs=[
            "确认撤销平仓 CO-20260304-ABCD1234",
        ],
    ),
    "close.query_status": NodeSeedSpec(
        node_name="close.query_status",
        product_type="option_close",
        intent_values=["close_order_order_query"],
        description="平仓订单状态查询。",
        sample_inputs=[
            "查询 OPTG-WFJJ202509030002 的状态",
            "CO-20260304-0001 现在怎样了",
        ],
    ),
}


# ============================================================
# 模板渲染
# ============================================================


_HEADER = """\
# Golden 种子收集 · {node_name}

> grill-with-docs 2026-05-10 第 4 决策落地 · 业务方填空，工程师转 jsonl

## 节点描述

**{description}**

| 字段 | 值 |
|---|---|
| 节点 | `{node_name}` |
| product_type | `{product_type}` |
| 合法 intent 枚举 | {intent_list} |

## 填空指南

- 每条 case 写一段自然语言（用户在企微群里可能说的原话）
- 只标 `expected.product_type` + `expected.intent`，参数细节不用标
- 至少填 6 条，建议覆盖：标准表达 / 缩写 / 错别字 / 多目标 / 边界场景
- 引用消息的 case，请把上一条客服消息填到 `quote_content`

## 示例输入（启发用，不是强制 case）

{sample_inputs_block}

## Case 槽位（按编号填）

"""

_CASE_SLOT = """\
### Case {idx}

```yaml
raw_content: "<填用户原话>"
quote_content: null  # 引用消息时填上一条客服话；无引用填 null
expected:
  product_type: {product_type}
  intent: <从合法 intent 枚举选一个>
notes: "<可选：填这条 case 想测什么场景>"
source: business_seed
```

"""


def render_seed_template(node_name: str, num_slots: int = 8) -> str:
    """渲染单节点的种子收集 markdown 模板。"""
    spec = NODE_REGISTRY.get(node_name)
    if spec is None:
        raise KeyError(
            f"Unknown node: {node_name}. "
            f"Registered: {sorted(NODE_REGISTRY.keys())}"
        )

    intent_list = (
        ", ".join(f"`{v}`" for v in spec.intent_values)
        if spec.intent_values
        else "(无 intent 字段，输出 list[TickerCandidate])"
    )
    sample_block = (
        "\n".join(f"- {s}" for s in spec.sample_inputs)
        if spec.sample_inputs
        else "(无)"
    )

    parts = [
        _HEADER.format(
            node_name=spec.node_name,
            description=spec.description,
            product_type=spec.product_type,
            intent_list=intent_list,
            sample_inputs_block=sample_block,
        )
    ]
    for i in range(1, num_slots + 1):
        parts.append(_CASE_SLOT.format(idx=i, product_type=spec.product_type))
    return "".join(parts)


__all__ = ["NODE_REGISTRY", "NodeSeedSpec", "render_seed_template"]
