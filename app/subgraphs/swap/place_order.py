"""互换下单内部图读取联合结果；候选选择与 Java 提交在外层确定性执行。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.fields import EvidenceError
from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ExpectedAction, SubgraphOutput, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import SwapInstruction
from app.subgraphs.swap.backend import prepare_swap_request
from app.subgraphs.swap.order_id import extract_order_ids


class SwapPlaceState(AgentState, total=False):
    """内部图只暂存本次请求参数，不保存旧订单副本。"""

    sp_params: dict[str, Any]


class SwapPlaceOutput(SubgraphOutput, total=False):
    """内部准备图把选择指针交给互换父图；主图仍使用更窄的 SubgraphOutput。"""

    swap_ticker_picks: list[dict[str, Any]] | None
    swap_counterparty_picks: dict[str, Any] | None


def _expected_action(orders: list[dict[str, Any]]) -> ExpectedAction:
    """Java 使用同一接口区分新建和补参，审计按是否带订单号记录动作。"""
    return "modify" if any(order.get("orderId") for order in orders) else "place"


@safe_node
async def swap_prepare(state: SwapPlaceState) -> dict[str, Any]:
    """读取参数和候选选择指针，所有语义来自本次唯一解析。"""
    parsed = SwapInstruction.model_validate(state.get("parsed_instruction") or {})
    if parsed.intent != "place_order_request":
        raise EvidenceError("互换下单节点收到其它业务动作")
    orders = [order.model_dump(exclude_none=True, exclude_unset=True) for order in parsed.orders]
    return {"sp_params": {"orderList": orders},
            "swap_ticker_picks": [pick.model_dump() for pick in parsed.ticker_picks],
            "swap_counterparty_picks": {"hasSignal": bool(parsed.counterparty_picks),
                "picks": [pick.model_dump() for pick in parsed.counterparty_picks]},
            "trace": [TraceEntry(node="swap_prepare", decision=f"orders={len(orders)}")]}


@safe_node
async def swap_validate(state: SwapPlaceState) -> dict[str, Any]:
    """验证字段来源与已有订单身份，不重算数量、金额或业务默认值。"""
    parsed = SwapInstruction.model_validate(state.get("parsed_instruction") or {})
    records = verify_instruction(parsed, state)
    allowed = set(extract_order_ids(state.get("raw_text")) + extract_order_ids(state.get("quote_content")))
    for order in parsed.orders:
        if order.order_id and order.order_id not in allowed:
            raise EvidenceError("互换订单号超出本次消息或引用范围")
    return {"field_records": records}


@safe_node
async def swap_place_result(state: SwapPlaceState) -> dict[str, Any]:
    """将准备好的接口参数写入业务对象，供候选选择和提交读取。"""
    orders = (state.get("sp_params") or {}).get("orderList") or []
    return {"expected_action": _expected_action(orders),
            "place_params": validated_place_params(orderList=orders),
            "trace": [TraceEntry(node="swap_place_result", decision=f"orders={len(orders)}")]}


def _after_prepare(state: SwapPlaceState) -> str:
    """参数错误时不继续验证或提交。"""
    return END if state.get("error") else "swap_validate"


def _after_validate(state: SwapPlaceState) -> str:
    """来源错误时停止写入业务对象。"""
    return END if state.get("error") else "swap_place_result"


def build_place_graph() -> CompiledStateGraph[SwapPlaceState, None, AgentState, SwapPlaceOutput]:
    """互换参数图只包含三个确定性阶段。"""
    graph = StateGraph(SwapPlaceState, input_schema=AgentState, output_schema=SwapPlaceOutput)
    graph.add_node("swap_prepare", swap_prepare)
    graph.add_node("swap_validate", swap_validate)
    graph.add_node("swap_place_result", swap_place_result)
    graph.add_edge(START, "swap_prepare")
    graph.add_conditional_edges("swap_prepare", _after_prepare, ["swap_validate", END])
    graph.add_conditional_edges("swap_validate", _after_validate, ["swap_place_result", END])
    graph.add_edge("swap_place_result", END)
    return graph.compile(name="swap_place_order")


@lru_cache(maxsize=1)
def get_place_graph() -> CompiledStateGraph[SwapPlaceState, None, AgentState, SwapPlaceOutput]:
    """调试入口复用编译图，业务会话由主图统一维护。"""
    return build_place_graph()


async def swap_place_order(state: AgentState) -> dict[str, Any]:
    """独立执行内部参数图，只返回子图契约允许的字段。"""
    return await get_place_graph().ainvoke(state)


@safe_node
async def swap_place_order_submit(state: AgentState) -> dict[str, Any]:
    """准备经过选择检查的原始请求，交父图独立清洗和提交。"""
    orders = (state.get("place_params") or {}).get("orderList") or []
    request_update = await prepare_swap_request(state, intent="place_order_request", order_list=orders)
    return {**request_update, "trace": [TraceEntry(node="swap_place_order_submit", decision=f"orders={len(orders)}")]}
