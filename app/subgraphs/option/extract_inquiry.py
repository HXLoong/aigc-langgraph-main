"""option.extract_inquiry 节点 · 期权询价参数提取（含 ticker resolver 集成）。

输入：raw_text + quote_content + history_messages
输出：state['place_params'] = {expected_action: "inquiry", orderList: [...]}
      state['tickers'] = list[TickerCandidate]（来自 ticker resolver）

**首次集成 ticker resolver**：
- LLM 提取询价参数（stockCode 字段保留用户原话）
- 节点同步调用 resolve_ticker(raw_text) 拿 from_goats=True 候选
- 写到 state['tickers']，供下游审计 / 后端调用使用

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_inquiry.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import _with_resolved_ticker, call_option_backend
from app.subgraphs.option.models import OptionInquiryParams
from app.subgraphs.ticker.resolver import resolve_ticker, resolve_ticker_full


#: 快速询价 / 雪球 / 参与型识别关键词（命中则不走 LLM，直传 GOATS instrument parser）
_FAST_INQUIRY_MARKERS = ("快速询价", "雪球", "参与型", "敲入", "敲出")


def _is_fast_inquiry(text: str) -> bool:
    """检测 raw_text 是否是快速询价 / 雪球类强信号场景。"""
    if not text:
        return False
    return any(m in text for m in _FAST_INQUIRY_MARKERS)


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
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    return (
        f"用户消息：{raw_content}\n\n"
        f"引用消息：{quote_content}\n\n"
        f"历史对话：\n{history_str}"
    )


@safe_node
async def option_extract_inquiry(state: AgentState) -> dict[str, Any]:
    """option.extract_inquiry 节点。

    出参约定：
    - place_params: {expected_action: "inquiry", orderList: [...]}
    - tickers: list[TickerCandidate]（resolver 输出，from_goats=True）
    - trace: 单条 TraceEntry，记录订单数 + 标的数
    """
    raw_text = state.get("raw_text", "") or ""

    # 0a. 快速询价 / 雪球 / 参与型 → 直接转发给 GOATS instrument parser，跳过 LLM 抽取
    # 与 Dify 工作流"判断快速询价"分支对齐：用户输入这类强信号关键词时，原文直传
    # GOATS endpoint 拿 parsed 字段（productType/tenor/knockInPrice/...），再带着这些
    # 字段调现有 option/operate backend 拿正式询价回复
    if _is_fast_inquiry(raw_text):
        from app.tools.goats_rfq import parse_rfq_instrument

        rfq_data = await parse_rfq_instrument(raw_text)
        if rfq_data:
            # 把 GOATS parser 返回的字段填到 optionRfq 调后端
            # 把 GOATS parser 字段透传给 backend (含 fuzzyCodeList / productSubtypeList 等扩展字段)
            option_rfq = {
                "chatType": rfq_data.get("chatType"),
                "chatInstrument": rfq_data.get("chatInstrument") or raw_text,
                "productType": rfq_data.get("productType"),
                "tenor": rfq_data.get("tenor"),
                "strike": [str(s) for s in (rfq_data.get("strike") or [])],
                "knockInPrice": [str(p) for p in (rfq_data.get("knockInPrice") or [])],
                "knockOutPrice": [str(p) for p in (rfq_data.get("knockOutPrice") or [])],
                "estimateMargin": [str(m) for m in (rfq_data.get("estimateMargin") or [])],
                "fuzzyCodeList": rfq_data.get("fuzzyCodeList") or [],
                "productSubtypeList": rfq_data.get("productSubtypeList") or [],
                "participateRate": [str(p) for p in (rfq_data.get("participateRate") or [])],
            }
            backend = await call_option_backend(
                state,
                intent="new_inquiry",
                option_rfq=option_rfq,
            )
            # 不写 place_params/tickers，让 render 走 step 5 直接透传 backend api_result
            return {
                **backend,
                "trace": [
                    TraceEntry(
                        node="option_extract_inquiry",
                        decision=f"fast_inquiry product={rfq_data.get('productType')}",
                        llm_output={"rfq_data": rfq_data},
                    )
                ],
            }

    # 0. 无效标的预检（代码格式但不在池→直接拒绝，不调 LLM）
    import re as _re_ticker
    _has_code_like = bool(_re_ticker.search(
        r"\d{5,6}[.\s]|[A-Z]{2,6}\d+|L\d{4,}", raw_text
    ))
    if _has_code_like:
        _tickers = await resolve_ticker(raw_text)
        if not _tickers:
            return {
                "place_params": {"expected_action": "inquiry", "orderList": []},
                "tickers": [],
                "error": "抱歉！标的代码（或标的名称）不在标的池内，无法自动报价，请联系对口销售或交易员。",
                "trace": [TraceEntry(node="option_extract_inquiry", decision="invalid_ticker")],
            }

    # 1. LLM 提取询价参数（standard 模型 + structured output）
    prompt = load_prompt("option", "extract_inquiry")
    llm = get_qwen_thinking().with_structured_output(OptionInquiryParams)
    user_message = _build_user_message(state)
    params: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # 2. ticker resolver 识别标的（含 HITL 信号）
    resolution = await resolve_ticker_full(raw_text)
    tickers = resolution.resolved
    order_list = [item.model_dump() for item in params.orderList]
    backend_order_list = [
        _with_resolved_ticker(dict(item), tickers, idx)
        for idx, item in enumerate(order_list)
    ]

    types = [item.optionType for item in params.orderList if item.optionType]
    decision = (
        f"action=inquiry,"
        f" orders={len(params.orderList)},"
        f" tickers={len(tickers)},"
        f" types={types},"
        f" hitl={len(resolution.hitl_pending)}"
    )

    backend = await call_option_backend(
        state,
        intent="new_inquiry",
        order_list=backend_order_list,
    )

    out: dict = {
        "place_params": {
            "expected_action": "inquiry",
            "orderList": order_list,
        },
        "tickers": tickers,
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_inquiry",
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


__all__ = ["option_extract_inquiry"]
