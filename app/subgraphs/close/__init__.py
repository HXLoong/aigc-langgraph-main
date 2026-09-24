"""close 子图（期权平仓，product_type=option_close）。

1 个意图节点 + 6 个意图节点 + close_unknown 兜底（拓扑见 graph.py）：持仓查询、平仓下单
（引用解析 → 订单拉取 → 证据提取 → 归一化 → 校验 → 提交的嵌套子图）、确认平仓、平仓撤单、
确认撤销平仓、平仓状态查询。目录名 `close` 沿用 ADR 0001 D6；prompts 目录与 product_type 用
`option_close`。
"""
from app.subgraphs.close.graph import build_close_graph

__all__ = ["build_close_graph"]
