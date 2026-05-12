"""swap.place_order 节点 · 互换下单/改单参数提取（P0 核心，最大节点）。

输入：raw_text + quote_content + history_messages
输出：state['place_params'] = {expected_action, orderList}
      state['tickers'] = list[TickerCandidate]（来自 ticker resolver）

关键约定：
- 互换下单/改单在 Java 端**共用同一个 `place_order_request` 类型**
  （ADR 0001 D5 / CONTEXT.md），靠 orderList[i].orderId 是否存在区分
- expected_action 由调用方推导：有 orderId → "modify"；否则 → "place"
- ★ 含 ticker resolver 集成（与 option.extract_inquiry 同模板）

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/place_order.md（3059 行，最大节点）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import resolve_ticker_full


def _format_history(history: list[Message] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    """组装 user message（4 个 Dify 输入变量）。"""
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    bot_name_list: list[str] = []
    return (
        f"raw_content: {raw_content}\n\n"
        f"quote_content: {quote_content}\n\n"
        f"history_query_str:\n{history_str}\n\n"
        f"bot_name_list: {bot_name_list}"
    )


def _expected_action(params: SwapPlaceOrderParams) -> str:
    """根据 orderList 中是否有 orderId 推导 expected_action。

    swap 下单/改单共用 place_order_request 意图（ADR 0001 D5 / CONTEXT.md）：
    - 任一订单有 orderId → "modify"
    - 全部 orderId=null → "place"
    """
    if any(item.orderId for item in params.orderList):
        return "modify"
    return "place"


@safe_node
async def swap_place_order(state: AgentState) -> dict[str, Any]:
    """swap.place_order 节点。

    出参约定：
    - place_params: {expected_action, orderList}
    - tickers: list[TickerCandidate]（resolver 输出，from_goats=True）
    - trace: 单条 TraceEntry，记录 action + 订单数 + 标的数
    """
    raw_text = state.get("raw_text", "") or ""

    # 1. LLM 提取下单参数
    prompt = load_prompt("swap", "place_order")
    llm = get_qwen_structured().with_structured_output(SwapPlaceOrderParams)
    user_message = _build_user_message(state)
    params: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # 2. ticker resolver 识别标的（独立通道，含 HITL 信号）
    resolution = await resolve_ticker_full(raw_text)
    tickers = resolution.resolved

    action = _expected_action(params)
    decision = (
        f"action={action},"
        f" orders={len(params.orderList)},"
        f" tickers={len(tickers)},"
        f" hitl={len(resolution.hitl_pending)}"
    )

    out: dict = {
        "place_params": {
            "expected_action": action,
            "orderList": [item.model_dump() for item in params.orderList],
        },
        "tickers": tickers,
        "trace": [
            TraceEntry(
                node="swap_place_order",
                decision=decision,
                llm_output={
                    "params": params.model_dump(),
                    "tickers_count": len(tickers),
                    "hitl_count": len(resolution.hitl_pending),
                },
            )
        ],
    }
    if resolution.hitl_pending:
        out["ticker_hitl_candidates"] = resolution.hitl_pending
    return out


__all__ = ["swap_place_order"]
