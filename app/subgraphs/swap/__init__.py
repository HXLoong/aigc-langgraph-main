"""swap 子图（互换）。

DSL v2 迁移（2026-08）：意图 → {下单(规整引用补参摘要 → 下单 → [标的/对手候选
选择链] → 前置清洗 → 互换开仓)、确认下单(→ 二次校验) / 确认撤单 / 确认改单、
撤单、查询} → END。旧 DSL 的手转股（hand_to_share）迭代链已整体删除。

已实施节点：
- swap.intent · 二级意图分类（6 个真实 SwapIntentionType + unknown_intent 兜底）
- swap.place_order · 下单/改单参数提取（含互换-规整引用补参摘要 + ticker resolver）
- swap.select_counterparty / swap.select_ticker · 引用消息候选交易对手/标的选择
- swap.place_order_submit · 前置清洗 + 互换开仓（真后端提交）
- swap.confirm · 确认下单（含二次校验）/ 确认撤单 / 确认改单（共用节点函数，按
  intent 动态切 prompt）
- swap.cancel · 撤单订单号提取
- swap.query_order · 查询订单状态

P2 辅助节点（不对应 intent，是 swap.place_order 的工具，按线上流量增量补）：
- swap.place_order_image / swap.place_order_excel / swap.image_recognize
"""
from app.subgraphs.swap.graph import build_swap_graph

__all__ = ["build_swap_graph"]
