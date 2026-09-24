"""swap 子图（互换）。

入口按 swap_input_mode 分三链（拓扑见 graph.py）：
- 文本：swap_intent → 下单（候选提取 → 归一化嵌套子图 → [选对手 ‖ 选标的 → apply_picks]
  或全新对手识别 → 提交）/ 确认（下单 / 撤单 / 改单共用 swap_confirm）/ 撤单 / 查单
- 图片：swap_image_order；Excel：swap_excel_order（转写证据 → 候选 → Code 归一化 → 提交）

证券识别交 Java（ADR 0025）。
"""
from app.subgraphs.swap.graph import build_swap_graph

__all__ = ["build_swap_graph"]
