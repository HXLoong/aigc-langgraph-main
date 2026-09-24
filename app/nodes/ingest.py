"""ingest 节点：从 Dify Workflow Run inputs 进入主图的薄入口。

ADR 0001 D6 + ADR 0015 修订：ingest 仅做最低校验，不再设 product_type 默认值。
product_type 由下游 `intent_route` 节点（ADR 0015 三层路由）负责。
"""
from __future__ import annotations

import uuid
from time import time
from typing import Any

from langgraph.types import Overwrite

from app.config import get_settings
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.observability.canary import is_canary_room
from app.observability.metrics import emit_canary_traffic


@safe_node
async def ingest(state: AgentState) -> dict[str, Any]:
    """入口节点：薄入口 + per-turn 输出重置。

    上游已由 `app/api/routes.py` 把 Dify inputs 解构成 9 个机器人上下文字段
    （contracts §2.1 §3.1）放进 state。本节点不做任何业务决策，
    product_type 路由完全交给 `intent_route`。

    一轮的边界只在这里维护（ADR 0024 D2）：
    - per-turn 输出：intent / reply_text / api_result / api_code / error 清空（否则 render 看到上一轮
      非空 reply_text 直接跳过本轮渲染）
    - per-turn 业务对象：tickers / place_params / cancel_params / confirm / query_filter /
      close_params / ticker_hitl_candidates / swap 选择链指针通道清空。评估核实没有任何业务
      节点把它们当"上一轮结果"读，唯一的读者是 render——残留会被渲染成"已收到撤单请求"
      （状态串线）。跨轮记忆只保留 history_messages（与入口字段）
    - trace：Overwrite 清空上一轮，本轮从 ingest 起记（@safe_node 会把自身条目写进 Overwrite）

    金丝雀监控：每条请求按 roomId 判定 is_canary，emit metric。
    灰度期间非 canary 流量计数 ≥ 1 触发告警（误切 agentUrl 兜底）。
    """
    room_id = state.get("room_id")
    emit_canary_traffic(is_canary=is_canary_room(room_id))
    updates: dict[str, Any] = {}
    if not state.get("trace_id"):
        # ADR 0004：单次调用关联 ID（API 入口 routes.py 已生成；此处兜底
        # 覆盖 eval 脚本 / harness 等直接 ainvoke 的路径）
        updates["trace_id"] = uuid.uuid4().hex
    now = time()
    previous_activity = state.get("last_activity_at")
    expired = (
        previous_activity is not None
        and now - previous_activity >= get_settings().conversation_idle_timeout_seconds
    )
    result: dict[str, Any] = {
        **updates,
        "last_activity_at": now,
        "session_status": "active",
        "reply_text": None,
        "api_result": None,
        "api_code": None,
        "error": None,
        # 意图由本轮子图重算；未知产品或早退不能回写旧意图。产品上下文仍供路由使用。
        "intent": "",
        # per-turn 业务对象（ADR 0024 D2）
        "expected_action": None,
        "field_records": Overwrite({}),
        "tickers": None,
        "place_params": None,
        "cancel_params": None,
        "confirm": None,
        "query_filter": None,
        "close_params": None,
        "ticker_hitl_candidates": None,
        "swap_counterparty_picks": None,
        "swap_ticker_picks": None,
        # 一轮边界：清上一轮 trace
        "trace": Overwrite([]),
    }
    if expired:
        result.update({
            "session_status": "expired",
            "product_type": "unknown",
            "intent": "",
            "history_messages": Overwrite([]),
            "last_confirmed_params": None,
            "conversation_orders": [],
            "reply_text": "会话已过期，请重新发送当前指令；如需确认订单，请引用最新订单消息。",
            "trace": Overwrite([TraceEntry(node="ingest", decision="session:expired")]),
        })
    return result
