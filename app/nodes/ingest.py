"""ingest 节点：从 Dify Workflow Run inputs 进入主图的薄入口。

ADR 0001 D6 + ADR 0015 修订：ingest 仅做最低校验，不再设 product_type 默认值。
product_type 由下游 `intent_route` 节点（ADR 0015 三层路由）负责。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.observability.canary import is_canary_room
from app.observability.metrics import emit_canary_traffic


@safe_node
async def ingest(state: AgentState) -> dict[str, Any]:
    """入口节点：薄入口 + per-turn 输出重置。

    上游已由 `app/api/routes.py` 把 Dify inputs 解构成 9 个机器人上下文字段
    （contracts §2.1 §3.1）放进 state。本节点不做任何业务决策，
    product_type 路由完全交给 `intent_route`。

    Per-turn 输出重置：reply_text / api_result / api_code / error 是当轮节点的产物，
    多轮 case 在 LangGraph checkpoint 模式下前一轮的值会留在 state，导致 render
    检测到非空 reply_text 直接 return {} 跳过本轮渲染，最终回复用旧值。ingest
    显式清空这些字段保证每轮干净起步。业务对象（tickers/history_messages/place_params
    等）保留不动，多轮上下文照常工作。

    G5.1 金丝雀监控：每条请求按 roomId 判定 is_canary，emit metric。
    F4.2 期间非 canary 流量计数 ≥ 1 触发告警（误切 Webhook 兜底）。
    """
    room_id = state.get("room_id")
    emit_canary_traffic(is_canary=is_canary_room(room_id))
    return {
        "reply_text": None,
        "api_result": None,
        "api_code": None,
        "error": None,
    }
