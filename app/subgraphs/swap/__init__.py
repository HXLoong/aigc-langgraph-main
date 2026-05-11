"""swap 子图（互换）。

ADR 0001 D5 + grill-with-docs 2026-05-10：10 节点（合并 3 个原 confirm 后）。
M2 阶段逐节点实施，每节点一 PR（grill 第 1 决策）。

当前已实施：
- swap.intent · 二级意图分类（7 个 SwapIntentionType 枚举值）

待实施（M2 后续 PR）：
- swap.place_order · 下单/改单参数提取（共用 schema，靠 orderId 区分）
- swap.confirm · 合并版（covers 3 个原 confirm 节点）
- swap.cancel + swap.cancel_extract
- swap.query_order
- swap.place_order_image / swap.place_order_excel
- swap.image_recognize / swap.hand_to_share
"""
from app.subgraphs.swap.graph import build_swap_graph

__all__ = ["build_swap_graph"]
