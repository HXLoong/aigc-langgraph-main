"""option.extract_inquiry · 期权询价子图（ADR 0024 D3：三条管线做成图边，错误归因到阶段）。

    START ─┬─ 快速询价关键词 → inquiry_fast_parse ─┬─ GOATS 解析成功 → inquiry_fast_submit → END
           │                                       └─ 解析为空 ↓
           └─ inquiry_precheck ─┬─ 代码型标的不在池 → inquiry_reject → END
                                └─ inquiry_extract(LLM) → inquiry_resolve(ticker) → inquiry_submit → END

- 只读阶段（GOATS 解析 / 标的预检 / LLM 抽取 / 标的解析）是 @io_node，挂 RetryPolicy；
  两个提交阶段调后端询价（建单），@safe_node 不重试
- 私有中间态 `iq_*` 住在 InquiryState，不外泄（output_schema=InquiryOutput）
- 每阶段一条 TraceEntry；终点节点另写一条 `option_extract_inquiry` 汇总条目，沿用既有
  decision 口径（`fast_inquiry product=` / `invalid_ticker` / `action=inquiry, orders=…`）
- 测试 monkeypatch 边界不变：resolve_ticker / resolve_ticker_full / get_qwen_thinking /
  call_option_backend 仍从本模块查找；GOATS 解析从 app.tools.goats_rfq 查找

归一化（OPT-07）：tenor / 百分号 / 名义本金 / 参与率由 `normalize.py` 确定性完成，
"/" 多值按笛卡尔积展开——LLM 不再承担格式换算。prompt：app/prompts/option/extract_inquiry.md。
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.candidates import (
    candidate_model,
    evidence_sources,
    evidence_user,
    unpack_candidates,
)
from app.extraction.fields import FieldRecord, merge_fields
from app.graph.business_params import validated_place_params
from app.graph.cascade import has_error
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import (
    AgentState,
    ErrorInfo,
    ExpectedAction,
    TickerCandidate,
    TraceEntry,
    merge_by_id,
)
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import _with_resolved_ticker, call_option_backend
from app.subgraphs.option.models import OptionInquiryParams, OptionInquiryRawParams, OptionOrderItem
from app.subgraphs.option.normalize import expand_inquiry_items
from app.subgraphs.option.prompting import EXTRACT_INPUTS
from app.subgraphs.option.sanitize import sanitize_order_list
from app.subgraphs.ticker.resolver import resolve_ticker, resolve_ticker_full

#: 快速询价 / 雪球 / 参与型识别关键词（命中则先走 GOATS instrument parser，不走 LLM）
_FAST_INQUIRY_MARKERS = ("快速询价", "雪球", "参与型", "敲入", "敲出")
#: 代码型标的：命中则先查标的池，不在池直接拒绝（不调 LLM）
_CODE_LIKE_RE = re.compile(r"\d{5,6}[.\s]|[A-Z]{2,6}\d+|L\d{4,}")
_INVALID_TICKER_REPLY = "抱歉！标的代码（或标的名称）不在标的池内，无法自动报价，请联系对口销售或交易员。"


def _is_fast_inquiry(text: str) -> bool:
    """检测 raw_text 是否是快速询价 / 雪球类强信号场景。"""
    return bool(text) and any(m in text for m in _FAST_INQUIRY_MARKERS)


CANDIDATE_MODEL = candidate_model(OptionInquiryRawParams)
SPEC = register(PromptSpec(
    category="option",
    name="extract_inquiry",
    output_model=CANDIDATE_MODEL,
    inputs=EXTRACT_INPUTS,
    user_builder=evidence_user,
))


class InquiryState(AgentState, total=False):
    """询价子图私有 State：AgentState + `iq_*` 中间态。"""

    iq_rfq_data: dict[str, Any] | None
    iq_reject_reply: str | None
    iq_raw_params: dict[str, Any]
    iq_field_records: dict[str, FieldRecord]
    iq_order_list: list[dict[str, Any]]
    iq_types: list[str]
    iq_backend_order_list: list[dict[str, Any]]
    iq_bindings: list[dict[str, Any]]
    iq_hitl: list[dict[str, Any]]


class InquiryOutput(TypedDict, total=False):
    """子图对 option 图 / 父图的写回面。"""

    expected_action: ExpectedAction | None
    place_params: dict[str, Any] | None
    tickers: list[TickerCandidate]
    ticker_hitl_candidates: list[dict[str, Any]] | None
    reply_text: str | None
    api_result: str | dict[str, Any] | list[Any] | None
    api_code: int | None
    trace: Annotated[list[TraceEntry], merge_by_id]
    error: ErrorInfo | None
    field_records: Annotated[dict[str, FieldRecord], merge_fields]


# ============================================================
# 阶段节点
# ============================================================


@io_node
async def inquiry_fast_parse(state: InquiryState) -> dict[str, Any]:
    """快速询价 / 雪球：原文直传 GOATS instrument parser 拿 parsed 字段（只读）。"""
    from app.tools.goats_rfq import parse_rfq_instrument

    raw_text = state.get("raw_text", "") or ""
    rfq_data = await parse_rfq_instrument(raw_text)
    return {
        "iq_rfq_data": rfq_data or None,
        "trace": [TraceEntry(node="inquiry_fast_parse", decision="parsed" if rfq_data else "empty")],
    }


@safe_node
async def inquiry_fast_submit(state: InquiryState) -> dict[str, Any]:
    """把 GOATS parser 字段透传给 option/operate 拿正式询价回复（建单，不重试）。"""
    raw_text = state.get("raw_text", "") or ""
    rfq_data = state.get("iq_rfq_data") or {}
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
    backend = await call_option_backend(state, intent="new_inquiry", option_rfq=option_rfq)
    # 不写 place_params / tickers，让 render 直接透传 backend api_result
    return {
        **backend,
        "trace": [
            TraceEntry(node="inquiry_fast_submit", decision=f"api_code={backend.get('api_code')}"),
            TraceEntry(
                node="option_extract_inquiry",
                decision=f"fast_inquiry product={rfq_data.get('productType')}",
                llm_output={"rfq_data": rfq_data},
            ),
        ],
    }


@safe_node
async def inquiry_precheck(state: InquiryState) -> dict[str, Any]:
    """无效标的预检：代码格式但不在池 → 标记拒绝，不调 LLM。"""
    raw_text = state.get("raw_text", "") or ""
    if not _CODE_LIKE_RE.search(raw_text):
        return {"iq_reject_reply": None, "trace": [TraceEntry(node="inquiry_precheck", decision="no_code_like")]}
    tickers = await resolve_ticker(raw_text)
    if tickers:
        return {"iq_reject_reply": None, "trace": [TraceEntry(node="inquiry_precheck", decision="code_in_pool")]}
    return {
        "iq_reject_reply": _INVALID_TICKER_REPLY,
        "trace": [TraceEntry(node="inquiry_precheck", decision="code_not_in_pool")],
    }


@safe_node
async def inquiry_reject(state: InquiryState) -> dict[str, Any]:
    """早退出口：标的不在池，写业务回复，不调后端。"""
    return {
        "expected_action": "inquiry",
        "place_params": validated_place_params(orderList=[]),
        "tickers": [],
        "reply_text": state.get("iq_reject_reply"),
        "trace": [
            TraceEntry(node="inquiry_reject", decision="invalid_ticker"),
            TraceEntry(node="option_extract_inquiry", decision="invalid_ticker"),
        ],
    }


@io_node
async def inquiry_extract(state: InquiryState) -> dict[str, Any]:
    """LLM 只产出候选与证据；未验证的输出不能进入归一化或后端。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(CANDIDATE_MODEL)
    candidates = CANDIDATE_MODEL.model_validate(await llm.ainvoke(messages))
    raw_params, records = unpack_candidates(
        OptionInquiryRawParams, candidates, evidence_sources(state), scope="option/inquiry",
    )
    return {
        "iq_raw_params": raw_params.model_dump(), "iq_field_records": records,
        "trace": [TraceEntry(node="inquiry_extract", decision=f"verified_fields={len(records)}")],
    }


@safe_node
async def inquiry_normalize(state: InquiryState) -> dict[str, Any]:
    """代码归一化与多值展开，并把证据绑定到展开后的每笔订单。"""
    raw_params = OptionInquiryRawParams.model_validate(state.get("iq_raw_params") or {})
    expanded: list[dict[str, Any]] = []
    records: dict[str, FieldRecord] = {}
    for index, raw_item in enumerate(raw_params.order_list):
        items = expand_inquiry_items([raw_item])
        prefix = f"option/inquiry.orderList.{index}."
        for item in items:
            canonical_item = OptionOrderItem.model_validate(item).model_dump()
            target = f"option/inquiry.orderList.{len(expanded)}."
            for path, record in (state.get("iq_field_records") or {}).items():
                if path.startswith(prefix):
                    alias = path[len(prefix):]
                    records[target + alias] = record.model_copy(update={
                        "value": canonical_item.get(alias), "locked": alias not in {"stockCode", "shortName"},
                    })
            expanded.append(item)
    params = OptionInquiryParams.model_validate({"orderList": expanded})
    order_list = sanitize_order_list([item.model_dump() for item in params.order_list])
    return {
        "iq_order_list": order_list,
        "iq_types": [item.option_type for item in params.order_list if item.option_type],
        "field_records": records,
        "trace": [TraceEntry(node="inquiry_normalize", decision=f"orders={len(order_list)}")],
    }


@safe_node
async def inquiry_resolve(state: InquiryState) -> dict[str, Any]:
    """ticker resolver 识别标的（含 HITL 信号）并按身份绑定到订单。"""
    raw_text = state.get("raw_text", "") or ""
    resolution = await resolve_ticker_full(raw_text)
    tickers = resolution.resolved
    backend_order_list: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for index, item in enumerate(state.get("iq_order_list") or []):
        backend_order, match_result = _with_resolved_ticker(dict(item), tickers)
        backend_order_list.append(backend_order)
        bindings.append({
            "order_index": index,
            "original_stock_code": item.get("stockCode"),
            "backend_stock_code": backend_order.get("stockCode"),
            "result": match_result,
        })
    return {
        "tickers": tickers,
        "iq_backend_order_list": backend_order_list,
        "iq_bindings": bindings,
        "iq_hitl": list(resolution.hitl_pending),
        "trace": [
            TraceEntry(
                node="inquiry_resolve",
                decision=f"tickers={len(tickers)},hitl={len(resolution.hitl_pending)}",
            )
        ],
    }


@safe_node
async def inquiry_submit(state: InquiryState) -> dict[str, Any]:
    """调真后端询价（建单，不重试）；汇总条目沿用 option_extract_inquiry 名。"""
    order_list = state.get("iq_order_list") or []
    tickers = state.get("tickers") or []
    hitl = state.get("iq_hitl") or []
    backend = await call_option_backend(
        state, intent="new_inquiry", order_list=state.get("iq_backend_order_list") or []
    )
    decision = (
        f"action=inquiry,"
        f" orders={len(order_list)},"
        f" tickers={len(tickers)},"
        f" types={state.get('iq_types') or []},"
        f" hitl={len(hitl)}"
    )
    out: dict[str, Any] = {
        "expected_action": "inquiry",
        "place_params": validated_place_params(orderList=order_list),
        "tickers": tickers,
        **backend,
        "trace": [
            TraceEntry(node="inquiry_submit", decision=f"api_code={backend.get('api_code')}"),
            TraceEntry(
                node="option_extract_inquiry",
                decision=decision,
                llm_output={
                    "raw_params": state.get("iq_raw_params"),
                    "tickers_count": len(tickers),
                    "hitl_count": len(hitl),
                    "ticker_bindings": state.get("iq_bindings") or [],
                },
            ),
        ],
    }
    if hitl:
        out["ticker_hitl_candidates"] = hitl
    return out


# ============================================================
# 拓扑
# ============================================================


def _route_start(state: InquiryState) -> str:
    return "inquiry_fast_parse" if _is_fast_inquiry(state.get("raw_text", "") or "") else "inquiry_precheck"


def _route_after_fast_parse(state: InquiryState) -> str:
    if has_error(state):
        return END
    return "inquiry_fast_submit" if state.get("iq_rfq_data") else "inquiry_precheck"


def _route_after_precheck(state: InquiryState) -> str:
    if has_error(state):
        return END
    return "inquiry_reject" if state.get("iq_reject_reply") else "inquiry_extract"


def _route_or_end(next_node: str):  # type: ignore[no-untyped-def]
    def _router(state: InquiryState) -> str:
        return END if has_error(state) else next_node

    return _router


def build_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, InquiryOutput]:
    g: StateGraph[InquiryState, None, AgentState, InquiryOutput] = StateGraph(InquiryState, input_schema=AgentState, output_schema=InquiryOutput)
    add_io_node(g, "inquiry_fast_parse", inquiry_fast_parse)
    g.add_node("inquiry_fast_submit", inquiry_fast_submit)
    g.add_node("inquiry_precheck", inquiry_precheck)
    g.add_node("inquiry_reject", inquiry_reject)
    add_io_node(g, "inquiry_extract", inquiry_extract)
    g.add_node("inquiry_normalize", inquiry_normalize)
    g.add_node("inquiry_resolve", inquiry_resolve)
    g.add_node("inquiry_submit", inquiry_submit)

    g.add_conditional_edges(START, _route_start, ["inquiry_fast_parse", "inquiry_precheck"])
    g.add_conditional_edges("inquiry_fast_parse", _route_after_fast_parse,
                            ["inquiry_fast_submit", "inquiry_precheck", END])
    g.add_conditional_edges("inquiry_precheck", _route_after_precheck,
                            ["inquiry_reject", "inquiry_extract", END])
    g.add_conditional_edges("inquiry_extract", _route_or_end("inquiry_normalize"), ["inquiry_normalize", END])
    g.add_conditional_edges("inquiry_normalize", _route_or_end("inquiry_resolve"), ["inquiry_resolve", END])
    g.add_conditional_edges("inquiry_resolve", _route_or_end("inquiry_submit"), ["inquiry_submit", END])
    g.add_edge("inquiry_fast_submit", END)
    g.add_edge("inquiry_reject", END)
    g.add_edge("inquiry_submit", END)
    return g.compile(name="option_extract_inquiry")


@lru_cache(maxsize=1)
def get_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, InquiryOutput]:
    return build_inquiry_graph()


async def option_extract_inquiry(state: AgentState) -> dict[str, Any]:
    """façade：跑询价子图并返回写回面（供直接调用 / 测试；option 图原生嵌入编译图）。"""
    return await get_inquiry_graph().ainvoke(state)


__all__ = [
    "InquiryOutput",
    "InquiryState",
    "build_inquiry_graph",
    "get_inquiry_graph",
    "option_extract_inquiry",
]
