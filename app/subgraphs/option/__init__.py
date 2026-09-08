"""option 子图（期权基础意图，不含平仓）。

Dify DSL v2 迁移（分支 feature/dify-dsl-migration，P2 option 域）：
8 节点 = 1 intent + 7 extract（不含 close_order_*，归 close 子图；不再含独立
改单流程——期权对已有订单的参数修改统一归 place_order_from_quote）。

已实施：
- option.intent · 期权 7 个基础意图分类 + unknown_intent（new_inquiry /
  place_order_from_quote / confirm_order / cancel_order_request /
  request_cancel_order / confirm_cancel_order / query_order_status /
  unknown_intent）
- option.extract_inquiry · 询价参数提取（new_inquiry）
- option.extract_place · 请求下单参数提取（place_order_from_quote）
- option.extract_confirm_place · 确认下单订单号+补参提取（confirm_order）
- option.extract_cancel_place · 取消下单订单号提取（cancel_order_request）
- option.extract_cancel · 请求撤单订单号提取（request_cancel_order）
- option.extract_confirm_cancel · 确认撤单订单号提取（confirm_cancel_order）
- option.extract_query · 查询参数提取（query_order_status）
"""
from app.subgraphs.option.graph import build_option_graph

__all__ = ["build_option_graph"]
