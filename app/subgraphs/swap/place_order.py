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

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.subgraphs.swap.backend import _with_resolved_ticker, call_swap_backend
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
    """组装 user message（对齐 Dify swap.place_order.md 的 user 模板）。

    Dify 模板（参见 app/prompts/swap/place_order.md 末尾）需要 5 个变量：
        swap_query / raw_content / quote_content / bot_name_list / shortname_list

    历史问题：旧版只塞 raw_content/quote_content/history_query_str/bot_name_list，
    LLM 看不到 swap_query 字段就拒绝提取 placeOrderShortname（交易对手）等需"逐字符
    在 swap_query 中找"的字段——表现为用户已明确写"交易对手：XXX"，模型仍输出 null。

    修复：swap_query 用 raw_content 兜底；shortname_list 暂传空字符串（后续 PR 可接
    TickerClient.list_counterparty 拉取真值）。
    """
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    bot_name_list: list[str] = state.get("bot_name_list", []) or []
    counterparty_list = state.get("counterparty_list", []) or []
    shortname_list_str = ", ".join(
        c.get("shortName", "") if isinstance(c, dict) else str(c)
        for c in counterparty_list
    ) if counterparty_list else ""
    return (
        f"swap_query：{raw_content}\n"
        f"-------\n"
        f"raw_content：{raw_content}\n"
        f"-------\n"
        f"quote_content：{quote_content}\n"
        f"-------\n"
        f"bot_name_list：{bot_name_list}\n"
        f"-------\n"
        f"shortname_list: {shortname_list_str}\n"
        f"-------"
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
    llm = get_qwen_complex().with_structured_output(SwapPlaceOrderParams)
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
    order_list = [item.model_dump() for item in params.orderList]
    backend_order_list = [
        _with_resolved_ticker(dict(item), tickers, idx)
        for idx, item in enumerate(order_list)
    ]

    decision = (
        f"action={action},"
        f" orders={len(params.orderList)},"
        f" tickers={len(tickers)},"
        f" hitl={len(resolution.hitl_pending)}"
    )

    # 3. 调真后端 POST /admin-api/swap-order/operate
    backend = await call_swap_backend(
        state,
        intent="place_order_request",
        order_list=backend_order_list,
    )

    # 4. backend 成功时把真订单号 merge 回 order_list[i].orderId
    # （让 render 渲染卡显示真单号 H-XXX，turn N+1 confirm 才能从 quote 抠到）
    if backend.get("api_code") == 0:
        data = backend.get("api_result")
        oids: list[str] = []
        if isinstance(data, dict) and data.get("orderId"):
            oids = [data["orderId"]]
        elif isinstance(data, list):
            oids = [
                item["orderId"]
                for item in data
                if isinstance(item, dict) and item.get("orderId")
            ]
        elif isinstance(data, str):
            # backend 返回文本如 "下单成功 H-20260514-XXX" → regex 抓 H-YYYYMMDD-NNNN
            import re as _re_oid
            oids = _re_oid.findall(r"H-\d{8}-\d+", data)
        for i, oid in enumerate(oids):
            if i < len(order_list) and oid:
                order_list[i]["orderId"] = oid

    out: dict = {
        "place_params": validated_place_params(expected_action=action, orderList=order_list),
        "tickers": tickers,
        **backend,
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
