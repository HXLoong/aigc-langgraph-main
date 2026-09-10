"""close.cancel_close 节点 · 平仓撤单订单号提取。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['cancel_params'] = {"cancelOrderNoList": [...]}

LLM：standard 模型 + with_structured_output（ADR 0010 强制规则）。
prompt：app/prompts/option_close/cancel_close.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import CancelCloseParams


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_cancel_close(state: AgentState) -> dict[str, Any]:
    """close.cancel_close 节点。

    出参约定：
    - cancel_params: dict 含 cancelOrderNoList
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    prompt = load_prompt("option_close", "cancel_close")
    llm = get_qwen_thinking().with_structured_output(CancelCloseParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_nos = list(result.cancel_order_no_list)

    # 正则兜底：LLM 未提取到时从消息中搜订单号
    if not order_nos:
        import re as _re
        _combined = f"{state.get('raw_text','')} {state.get('quote_content','')}"
        _patterns = [
            r"CO-\d{8}-[A-Z0-9]{4,16}",
            r"Q-\d{8}-\d{8,12}",
            r"OPTG?-[A-Z]{4,}\d{0,10}",
        ]
        for _pat in _patterns:
            for _m in _re.findall(_pat, _combined):
                if _m not in order_nos:
                    order_nos.append(_m)

    # 会话订单兜底：取最近订单号
    if not order_nos:
        _conv_orders = state.get("conversation_orders", []) or []
        if _conv_orders:
            _last = _conv_orders[-1]
            _last_oid = _last.get("orderId") or _last.get("orderCode") or ""
            if _last_oid:
                order_nos = [_last_oid]

    # 真后端调用（Dify 全 6 分支均汇入 期权平仓-参数聚合 → 期权平仓[code]，
    # cancel_close 此前遗漏了这一跳——P0 payload 对齐项，见 close/backend.py）
    req_vo = build_close_order_req_vo(cancel_order_no_list=order_nos)
    backend = await call_close_backend(
        state,
        intent="close_order_cancel_request",
        close_order_req_vo=req_vo,
    )

    return {
        "cancel_params": validated_cancel_params(cancelOrderNoList=order_nos),
        **backend,
        "trace": [
            TraceEntry(
                node="close_cancel_close",
                decision=f"orders={len(order_nos)}",
                llm_output={"cancelOrderNoList": order_nos},
            )
        ],
    }


__all__ = ["close_cancel_close"]
