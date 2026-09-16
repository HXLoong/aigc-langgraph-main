"""close 子图（期权平仓）。

ADR 0001 D5/D6 + grill-with-docs 第 2 决策：
独立 product_type "option_close"（一级路由判定后进此子图），含 7 节点。

当前已实施（7 节点）：
- close.intent · 6 个 close_order_* 意图分类 + unknown_intent
- close.holding_query · 持仓查询
- close.place_close · 平仓下单参数提取
- close.confirm_close · 确认平仓（确定性，去 LLM）
- close.cancel_close · 平仓撤单（确定性，去 LLM）
- close.confirm_cancel · 确认撤销平仓（确定性，去 LLM）
- close.query_status · 平仓订单状态查询（确定性，去 LLM）

注：目录名 `close` 沿用 ADR 0001 D6；prompts 目录与 product_type 用
`option_close` 与 Dify YAML 原命名对齐。
"""
from app.subgraphs.close.graph import build_close_graph

__all__ = ["build_close_graph"]
