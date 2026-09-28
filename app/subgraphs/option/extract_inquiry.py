"""普通期权询价子图：读取联合解析 → 来源检查 → Java 提交。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, SubgraphOutput, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import OptionInstruction
from app.subgraphs.option.backend import prepare_option_request


class InquiryState(AgentState, total=False):
    """询价私有中间态，只保存本次待提交的参数。"""

    iq_order_list: list[dict[str, Any]]


InquiryOutput = SubgraphOutput


@safe_node
async def inquiry_prepare(state: InquiryState) -> dict[str, Any]:
    """读取同一次解析结果，不展开或换算业务参数。"""
    parsed = OptionInstruction.model_validate(state.get("parsed_instruction") or {})
    if parsed.intent != "new_inquiry":
        raise ValueError("询价子图不能执行其它业务动作")
    orders = [order.model_dump(exclude_none=True, exclude_unset=True) for order in parsed.orders]
    return {"iq_order_list": orders,
            "trace": [TraceEntry(node="inquiry_prepare", decision=f"orders={len(orders)}")]}


@safe_node
async def inquiry_validate(state: InquiryState) -> dict[str, Any]:
    """提交前检查结构与来源，业务数值和证券有效性由 Java 判断。"""
    parsed = OptionInstruction.model_validate(state.get("parsed_instruction") or {})
    return {"field_records": verify_instruction(parsed, state)}


@safe_node
async def inquiry_submit(state: InquiryState) -> dict[str, Any]:
    """准备完整询价请求；父图清洗后提交，写请求不重试。"""
    orders = state.get("iq_order_list") or []
    result = await prepare_option_request(state, intent="new_inquiry", order_list=orders)
    return {"expected_action": "inquiry", "place_params": validated_place_params(orderList=orders),
            **result, "trace": [TraceEntry(node="inquiry_submit", decision=f"orders={len(orders)}")]}


def _after_prepare(state: InquiryState) -> str:
    """读取失败即结束，避免空参数进入后端。"""
    return END if state.get("error") else "inquiry_validate"


def _after_validate(state: InquiryState) -> str:
    """来源检查失败即结束，不发起业务写入。"""
    return END if state.get("error") else "inquiry_submit"


def build_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, SubgraphOutput]:
    """以独立确定性节点构建询价流程，模型请求数恒为零。"""
    graph = StateGraph(InquiryState, input_schema=AgentState, output_schema=SubgraphOutput)
    graph.add_node("inquiry_prepare", inquiry_prepare)
    graph.add_node("inquiry_validate", inquiry_validate)
    graph.add_node("inquiry_submit", inquiry_submit)
    graph.add_edge(START, "inquiry_prepare")
    graph.add_conditional_edges("inquiry_prepare", _after_prepare, ["inquiry_validate", END])
    graph.add_conditional_edges("inquiry_validate", _after_validate, ["inquiry_submit", END])
    graph.add_edge("inquiry_submit", END)
    return graph.compile(name="option_extract_inquiry")


@lru_cache(maxsize=1)
def get_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, SubgraphOutput]:
    """供节点调试复用编译图，不保存会话 checkpoint。"""
    return build_inquiry_graph()


async def option_extract_inquiry(state: AgentState) -> dict[str, Any]:
    """独立节点执行入口只返回询价子图写回面。"""
    return await get_inquiry_graph().ainvoke(state)
