"""互换下单候选与确定性归一化的原生子图；提交由外层节点完成。"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.candidates import candidate_model, evidence_sources, verify_candidates
from app.graph.business_params import validated_place_params
from app.graph.cascade import has_error
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ExpectedAction, SubgraphOutput, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.candidate_scope import constrain_candidates
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates
from app.subgraphs.swap.quote_hints import refine_quote_hints


def _format_counterparty_list(counterparties: list[dict[str, Any]] | None) -> str:
    return ", ".join(c.get("shortName", "") for c in counterparties or [] if isinstance(c, dict))


def _build_user_message(
    state: AgentState, hints: Mapping[str, Any], prompt_name: str | None = None,
) -> str:
    return blocks.source_payload(state, context={
        "counterparties": state.get("swap_counterparties") or [],
        "quote_hints": hints.get("quote_param_hints", ""),
    })


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


def _expected_action(params: SwapPlaceOrderParams) -> ExpectedAction:
    return "modify" if any(item.order_id for item in params.order_list) else "place"


@io_node
async def swap_extract_candidates(state: SwapPlaceState) -> dict[str, Any]:
    messages, prompt_name = SPEC.build_messages(state)
    candidates = CANDIDATE_MODEL.model_validate(
        await get_qwen_complex().with_structured_output(CANDIDATE_MODEL).ainvoke(messages)
    )
    verify_candidates(candidates, evidence_sources(state))
    before = candidates.model_dump(by_alias=True)
    candidates = constrain_candidates(candidates, evidence_sources(state))
    after = candidates.model_dump(by_alias=True)
    changes = []
    if len(before["orderList"]) != len(after["orderList"]):
        changes.append({"field": "orderList", "change": "scope_restricted"})
    else:
        for index, (old, new) in enumerate(zip(before["orderList"], after["orderList"], strict=True)):
            for field, value in new.items():
                if old.get(field) != value:
                    changes.append({"field": f"orderList.{index}.{field}",
                                    "change": "omitted" if value is None else "evidence_scoped"})
    return {
        "sp_candidates": after, "sp_prompt_name": prompt_name,
        "trace": [TraceEntry(node="swap_extract_candidates", decision=f"constraints={len(changes)}",
                             llm_output={"prompt_name": prompt_name, "candidate_changes": changes})],
    }


@safe_node
async def swap_normalize(state: SwapPlaceState) -> dict[str, Any]:
    candidates = CANDIDATE_MODEL.model_validate(state.get("sp_candidates") or {})
    params, records = normalize_candidates(candidates, evidence_sources(state))
    if not params.order_list:
        return {
            "place_params": validated_place_params(orderList=[]),
            "reply_text": "未识别到有效订单，请提供标的、数量和操作。",
        }
    return {
        "sp_params": params.model_dump(), "field_records": records,
        "trace": [TraceEntry(node="swap_normalize", decision=f"orders={len(params.order_list)}")],
    }


@safe_node
async def swap_place_result(state: SwapPlaceState) -> dict[str, Any]:
    params = SwapPlaceOrderParams.model_validate(state.get("sp_params") or {})
    action = _expected_action(params)
    return {
        "expected_action": action,
        "place_params": validated_place_params(orderList=[item.model_dump() for item in params.order_list]),
        "trace": [TraceEntry(
            node="swap_place_order",
            decision=f"action={action}, orders={len(params.order_list)},instrument_resolution=backend",
            llm_output={"prompt_name": state.get("sp_prompt_name"), "params": params.model_dump()},
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
    graph.add_node("swap_place_result", swap_place_result)
    graph.add_edge(START, "swap_extract_candidates")
    for current, next_node in (
        ("swap_extract_candidates", "swap_normalize"),
        ("swap_normalize", "swap_place_result"),
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
