"""互换下单候选、确定性归一化、GOATS 绑定的原生子图；提交由外层节点完成。"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.candidates import candidate_model, evidence_sources, verify_candidates
from app.extraction.fields import FieldRecord
from app.graph.business_params import validated_place_params
from app.graph.cascade import has_error
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ExpectedAction, SubgraphOutput, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.backend import _with_resolved_ticker, call_swap_backend
from app.subgraphs.swap.candidate_scope import constrain_candidates
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates
from app.subgraphs.swap.quote_hints import refine_quote_hints
from app.subgraphs.ticker.resolver import resolve_ticker_full


def _format_counterparty_list(counterparties: list[dict[str, Any]] | None) -> str:
    return ", ".join(c.get("shortName", "") for c in counterparties or [] if isinstance(c, dict))


def _build_user_message(
    state: AgentState, hints: Mapping[str, Any], prompt_name: str | None = None,
) -> str:
    return json.dumps({
        "sources": evidence_sources(state),
        "counterparties": state.get("swap_counterparties") or [],
        "quote_hints": hints.get("quote_param_hints", ""),
    }, ensure_ascii=False)


def _user_from_state(state: AgentState) -> str:
    hints = refine_quote_hints(state.get("quote_content"), state.get("raw_text") or "")
    return _build_user_message(state, hints)


CANDIDATE_MODEL = candidate_model(SwapPlaceOrderParams)
SPEC = register(PromptSpec(
    category="swap", name="place_order", output_model=CANDIDATE_MODEL,
    inputs=("raw_text", "quote_content", "history_messages", "swap_counterparties", "conversation_id"),
    user_builder=_user_from_state, gray=True,
))


class SwapPlaceState(AgentState, total=False):
    sp_candidates: dict[str, Any]
    sp_params: dict[str, Any]
    sp_prompt_name: str
    sp_bindings: list[dict[str, Any]]


def _expected_action(params: SwapPlaceOrderParams) -> ExpectedAction:
    return "modify" if any(item.order_id for item in params.order_list) else "place"


@io_node
async def swap_extract_candidates(state: SwapPlaceState) -> dict[str, Any]:
    messages, prompt_name = SPEC.build_messages(state)
    candidates = CANDIDATE_MODEL.model_validate(
        await get_qwen_complex().with_structured_output(CANDIDATE_MODEL).ainvoke(messages)
    )
    verify_candidates(candidates, evidence_sources(state))
    candidates = constrain_candidates(candidates, evidence_sources(state))
    return {"sp_candidates": candidates.model_dump(by_alias=True), "sp_prompt_name": prompt_name}


@safe_node
async def swap_normalize(state: SwapPlaceState) -> dict[str, Any]:
    candidates = CANDIDATE_MODEL.model_validate(state.get("sp_candidates") or {})
    params, records = normalize_candidates(candidates, evidence_sources(state))
    if not params.order_list:
        return {
            "place_params": validated_place_params(orderList=[]), "tickers": [],
            "reply_text": "未识别到有效订单，请提供标的、数量和操作。",
        }
    return {
        "sp_params": params.model_dump(), "field_records": records,
        "trace": [TraceEntry(node="swap_normalize", decision=f"orders={len(params.order_list)}")],
    }


@safe_node
async def swap_resolve(state: SwapPlaceState) -> dict[str, Any]:
    # The ticker subgraph owns its leaf retries; do not retry the complete resolver again.
    params = SwapPlaceOrderParams.model_validate(state.get("sp_params") or {})
    # These are syntax labels for market enums, not a security/name data dictionary.
    markets = {"HK_STOCK": "港股", "US_STOCK": "美股", "A_SHARE": "A股"}
    query_names: dict[str, str] = {}
    for item in params.order_list:
        name = (item.place_order_wind_code or "").strip()
        if name:
            hint = markets.get(item.place_order_transaction_type or "", "")
            query_names[f"{hint} {name}".strip()] = name
    resolution = await resolve_ticker_full(
        state.get("raw_text") or "", filter_order_context=True,
        counterparty_shortnames=[
            c["shortName"] for c in state.get("swap_counterparties") or []
            if isinstance(c.get("shortName"), str)
        ],
        candidate_keywords=list(query_names),
    )
    # Preserve the original extraction identity after querying with an explicit market hint.
    tickers = []
    for ticker in resolution.resolved:
        if hasattr(ticker, "source_keywords"):
            names = list(ticker.source_keywords)
            names.extend(query_names[k] for k in ticker.source_keywords if k in query_names)
            ticker = ticker.model_copy(update={"source_keywords": list(dict.fromkeys(names))})
        tickers.append(ticker)
    orders, bindings = [], []
    records: dict[str, FieldRecord] = {}
    for index, item in enumerate(params.order_list):
        order, match = _with_resolved_ticker(item.model_dump(), tickers)
        orders.append(order)
        bindings.append({"order_index": index, "original_wind_code": item.place_order_wind_code,
                         "resolved_wind_code": order.get("placeOrderWindCode"), "result": match})
        if match.startswith("matched"):
            path = f"swap/place_order.orderList.{index}.placeOrderWindCode"
            previous = (state.get("field_records") or {}).get(path)
            if previous is not None:
                records[path + ".candidate"] = previous
            records[path] = FieldRecord(
                value=order["placeOrderWindCode"], source="goats",
                evidence=order["placeOrderWindCode"], origin="securities-instrument",
            )
    return {
        "sp_params": {"orderList": orders}, "sp_bindings": bindings,
        "tickers": tickers, "field_records": records,
        "ticker_hitl_candidates": list(resolution.hitl_pending) or None,
    }


@safe_node
async def swap_place_result(state: SwapPlaceState) -> dict[str, Any]:
    params = SwapPlaceOrderParams.model_validate(state.get("sp_params") or {})
    action = _expected_action(params)
    tickers, hitl = state.get("tickers") or [], state.get("ticker_hitl_candidates") or []
    return {
        "expected_action": action,
        "place_params": validated_place_params(orderList=[item.model_dump() for item in params.order_list]),
        "trace": [TraceEntry(
            node="swap_place_order",
            decision=f"action={action}, orders={len(params.order_list)}, tickers={len(tickers)}, hitl={len(hitl)}",
            llm_output={"prompt_name": state.get("sp_prompt_name"), "params": params.model_dump(),
                        "ticker_bindings": state.get("sp_bindings") or [], "tickers_count": len(tickers),
                        "hitl_count": len(hitl)},
        )],
    }


def _next_stage(next_node: str) -> Callable[[SwapPlaceState], str]:
    def route(state: SwapPlaceState) -> str:
        return END if has_error(state) or state.get("reply_text") else next_node
    return route


def build_place_graph() -> CompiledStateGraph[SwapPlaceState, None, AgentState, SubgraphOutput]:
    graph: StateGraph[SwapPlaceState, None, AgentState, SubgraphOutput] = StateGraph(SwapPlaceState, input_schema=AgentState, output_schema=SubgraphOutput)
    add_io_node(graph, "swap_extract_candidates", swap_extract_candidates)
    graph.add_node("swap_normalize", swap_normalize)
    graph.add_node("swap_resolve", swap_resolve)
    graph.add_node("swap_place_result", swap_place_result)
    graph.add_edge(START, "swap_extract_candidates")
    for current, next_node in (
        ("swap_extract_candidates", "swap_normalize"),
        ("swap_normalize", "swap_resolve"),
        ("swap_resolve", "swap_place_result"),
    ):
        graph.add_conditional_edges(current, _next_stage(next_node), [next_node, END])
    graph.add_edge("swap_place_result", END)
    return graph.compile(name="swap_place_order")


@lru_cache(maxsize=1)
def get_place_graph() -> CompiledStateGraph[SwapPlaceState, None, AgentState, SubgraphOutput]:
    return build_place_graph()


async def swap_place_order(state: AgentState) -> dict[str, Any]:
    return await get_place_graph().ainvoke(state)


_ORDER_ID_PATTERN = re.compile(r"H-\d{8}-\d+")


@safe_node
async def swap_place_order_submit(state: AgentState) -> dict[str, Any]:
    """swap.place_order_submit 节点（互换开仓-前置清洗 → 互换开仓）。

    汇总 swap_place_order（+ 可选 swap_select_counterparty / swap_select_ticker
    覆盖后）的 state['place_params']，调真后端 POST
    /admin-api/swap-order/operate，并把后端返回的真实订单号回写到
    orderList[i].orderId，供结构化 state、trace 和输出观测使用。用户可见回复始终
    原样透传 api_result，不使用回写后的参数重新渲染。
    """
    place_params = state.get("place_params") or {}
    order_list = [dict(item) for item in (place_params.get("orderList") or [])]

    backend = await call_swap_backend(
        state,
        intent="place_order_request",
        order_list=order_list,
    )

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
            oids = _ORDER_ID_PATTERN.findall(data)
        for i, oid in enumerate(oids):
            if i < len(order_list) and oid:
                order_list[i]["orderId"] = oid

    return {
        "place_params": validated_place_params(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_place_order_submit",
                decision=f"orders={len(order_list)},api_code={backend.get('api_code')}",
            )
        ],
    }


__all__ = ["swap_place_order", "swap_place_order_submit"]
