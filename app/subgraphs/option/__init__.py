"""option 子图（期权基础意图，不含平仓）。

ADR 0001 D5/D6 + ADR 0011 二次修订 + grill-with-docs 第 2 决策：
6 节点 = 1 intent + 5 extract（不含 close_order_*，归 close 子图）。

当前已实施：
- option.intent · 期权 10 个基础意图分类（new_inquiry / place_order_from_quote /
  request_modify_order / request_cancel_order / cancel_order_request /
  confirm_order / confirm_cancel_order / confirm_modify_order /
  query_order_status / unknown_intent）

待实施（M2 后续 PR，每节点一 PR）：
- option.extract_inquiry · 询价参数提取
- option.extract_place_or_modify · 下单/改单参数（共用 schema）
- option.extract_cancel · 撤单参数
- option.extract_confirm · 3 种确认参数（合并版）
- option.extract_query · 查询参数
"""
from app.subgraphs.option.graph import build_option_graph

__all__ = ["build_option_graph"]
