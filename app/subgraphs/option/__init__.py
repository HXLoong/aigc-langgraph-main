"""option 子图（期权开仓基础意图，不含平仓）。

1 个 LLM 意图节点 + 7 个意图节点（拓扑见 graph.py）：询价走「证据提取 → 归一化 → 提交」嵌套子图，
其余 6 个意图（请求下单 / 确认下单 / 取消下单 / 请求撤单 / 确认撤单 / 查单）为确定性代码节点。
期权无独立改单流程，对已有订单的参数修改统一归 place_order_from_quote。
"""
from app.subgraphs.option.graph import build_option_graph

__all__ = ["build_option_graph"]
