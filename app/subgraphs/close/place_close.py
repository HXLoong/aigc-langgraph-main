"""平仓下单内部子图：读取联合结果 → 选择范围检查 → Java 提交。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, SubgraphOutput, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import CloseInstruction
from app.subgraphs.close.backend import prepare_close_request
from app.subgraphs.close.selection import validate_close_selection


class PlaceCloseState(AgentState, total=False):
    """平仓私有参数不泄漏到父图。"""

    pc_close_orders: list[dict[str, Any]]


PlaceCloseOutput = SubgraphOutput


@safe_node
async def place_close_prepare(state: PlaceCloseState) -> dict[str, Any]:
    """读取用户指定的接口值；金额、比例和执行方式不在代码里重算。"""
    parsed = CloseInstruction.model_validate(state.get("parsed_instruction") or {})
    if parsed.intent != "close_order_request":
        raise ValueError("平仓下单节点不能执行其它动作")
    records = verify_instruction(parsed, state)
    orders = [item.model_dump(exclude_none=True, exclude_unset=True) for item in parsed.orders]
    return {"pc_close_orders": orders, "field_records": records,
            "trace": [TraceEntry(node="place_close_prepare", decision=f"orders={len(orders)}")]}


@safe_node
async def place_close_validate(state: PlaceCloseState) -> dict[str, Any]:
    """检查订单身份与本次引用范围，证券和业务数值交 Java 验证。"""
    validate_close_selection(state, state.get("pc_close_orders") or [])
    return {"trace": [TraceEntry(node="place_close_validate", decision="scope_verified")]}


@safe_node
async def place_close_submit(state: PlaceCloseState) -> dict[str, Any]:
    """准备全部选定订单；父图清洗后一次提交，不重试模型或交易。"""
    orders = state.get("pc_close_orders") or []
    payload = {"closeOrderList": orders}
    request_update = await prepare_close_request(state, intent="close_order_request", close_order_req_vo=payload)
    return {"expected_action": "close", "close_params": validated_close_params(**payload), **request_update,
            "trace": [TraceEntry(node="place_close_submit", decision=f"orders={len(orders)}")]}


def _after_prepare(state: PlaceCloseState) -> str:
    """参数结构错误时停止执行。"""
    return END if state.get("error") else "place_close_validate"


def _after_validate(state: PlaceCloseState) -> str:
    """选择范围不确定时停止业务提交。"""
    return END if state.get("error") else "place_close_submit"


def build_place_close_graph() -> CompiledStateGraph[PlaceCloseState, None, AgentState, SubgraphOutput]:
    """三个阶段都为确定性节点，前置只读上下文在主图唯一解析前准备。"""
    graph = StateGraph(PlaceCloseState, input_schema=AgentState, output_schema=SubgraphOutput)
    graph.add_node("place_close_prepare", place_close_prepare)
    graph.add_node("place_close_validate", place_close_validate)
    graph.add_node("place_close_submit", place_close_submit)
    graph.add_edge(START, "place_close_prepare")
    graph.add_conditional_edges("place_close_prepare", _after_prepare, ["place_close_validate", END])
    graph.add_conditional_edges("place_close_validate", _after_validate, ["place_close_submit", END])
    graph.add_edge("place_close_submit", END)
    return graph.compile(name="close_place_close")


@lru_cache(maxsize=1)
def get_place_close_graph() -> CompiledStateGraph[PlaceCloseState, None, AgentState, SubgraphOutput]:
    """供调试入口复用无 checkpoint 的编译图。"""
    return build_place_close_graph()


async def close_place_close(state: AgentState) -> dict[str, Any]:
    """独立执行平仓内部图并返回限定写回字段。"""
    return await get_place_close_graph().ainvoke(state)
