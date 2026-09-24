"""意图级 runner：只跑意图子链，冻结上下文，意图集评测只依赖 LLM。

主图在意图之后还会参数抽取、调后端下单/查询、render、persist，并用上一轮机器人回复拼引用；
意图集只评 product_type / intent，所以这里只组装识别意图所需的节点：

    START → ingest → pre_route → intent_route → {swap_intent | option_intent | close_intent} → END

`swap_extraction=True` 时在 swap place_order_request 之后追加 swap 下单参数抽取子图
（候选抽取 → 归一化 → 结果，纯 LLM + Code），供标的原文评估读 place_params；提交节点不在图里。

每轮上下文由 fixture 冻结（quote_content / history / prev_product_type），逐轮独立执行，
不回放上一轮回复，也不依赖 checkpointer。节点均为生产实现，任何后端调用都会暴露为网络错误。
交易对手列表（生产由 Java 入参携带）取仓库内 mock 授权上下文，与回放模式在 CI 里从 mock_api
拉到的数据同源，进程内读取、不走网络。

仍需上一轮真实回复的用例（`requires_replay`）不能走这里，由 langfuse_eval 转主图 + mock_api 回放。
"""
from __future__ import annotations

import importlib
import json
import secrets
from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.api.turn_state import inputs_to_state
from app.graph.retry import add_io_node
from app.graph.state import AgentState, Message
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.pre_route import pre_route
from app.subgraphs.close.intent import close_intent
from app.subgraphs.option.intent import option_intent
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.place_order import build_place_graph
from harness.intent_context import requires_replay

#: 仓库内 mock 授权对手上下文（与回放模式 CI 从 mock_api 拉到的同源）。运行时导入：mock_api 不在
#: mypy strict 范围内（app/ harness/），静态导入会把整个 mock 后端拉进类型检查
COUNTERPARTIES: list[dict[str, Any]] = importlib.import_module("mock_api.backend.fixtures").COUNTERPARTIES

_PRODUCT_NODES = {"swap": "swap_intent", "option": "option_intent", "option_close": "close_intent"}


def _route_after_ingest(state: AgentState) -> str:
    return END if state.get("error") is not None else "pre_route"


def _route_after_intent_route(state: AgentState) -> str:
    """错误或 unknown 收尾；swap 图片 / Excel 链在生产里跳过意图识别，这里同样收尾。"""
    if state.get("error") is not None:
        return END
    product = state.get("product_type") or "unknown"
    if product == "swap" and (state.get("swap_input_mode") or "text") != "text":
        return END
    return _PRODUCT_NODES.get(product, END)


def _route_after_swap_intent(state: AgentState) -> str:
    if state.get("error") is None and state.get("intent") == "place_order_request":
        return "swap_place_order"
    return END


def build_intent_graph(
    *, swap_extraction: bool = False
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """组装意图子链；不挂 checkpointer（上下文由 fixture 冻结后逐轮注入）。"""
    g: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    g.add_node("ingest", ingest)
    g.add_node("pre_route", pre_route)
    add_io_node(g, "intent_route", intent_route)
    add_io_node(g, "swap_intent", swap_intent)
    add_io_node(g, "option_intent", option_intent)
    add_io_node(g, "close_intent", close_intent)

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", _route_after_ingest, ["pre_route", END])
    g.add_edge("pre_route", "intent_route")
    g.add_conditional_edges("intent_route", _route_after_intent_route, [*_PRODUCT_NODES.values(), END])
    if swap_extraction:
        g.add_node("swap_place_order", build_place_graph())
        g.add_conditional_edges("swap_intent", _route_after_swap_intent, ["swap_place_order", END])
        g.add_edge("swap_place_order", END)
    else:
        g.add_edge("swap_intent", END)
    g.add_edge("option_intent", END)
    g.add_edge("close_intent", END)
    return g.compile(name="intent_chain")


def turn_state(turn: Mapping[str, Any], *, conversation_id: str) -> AgentState:
    """一轮 fixture → 入口 state：与生产同一入口（inputs_to_state），再注入冻结上下文。"""
    state: dict[str, Any] = dict(
        inputs_to_state(
            {
                "rawContent": turn.get("send_text", ""),
                "quoteContent": turn.get("quote_content") or None,
                "messageId": secrets.randbelow(900_000_000_000_000) + 100_000_000_000_000,
                "roomId": "eval-room",
                "userId": "eval-user",
                "guid": "",
                "at_bot": bool(turn.get("at_bot", True)),
                "optionCounterparties": json.dumps(COUNTERPARTIES, ensure_ascii=False),
                "swapCounterparties": json.dumps(COUNTERPARTIES, ensure_ascii=False),
            }
        )
    )
    state["conversation_id"] = conversation_id
    history = [
        Message(role=item["role"], content=item["content"]) for item in turn.get("history") or []
    ]
    if history:
        state["history_messages"] = history
    if turn.get("prev_product_type"):
        # intent_route 第 3 层多轮粘性读取上一轮 product_type
        state["product_type"] = turn["prev_product_type"]
    return state  # type: ignore[return-value]


async def run_turn(
    graph: Any,
    turn: Mapping[str, Any],
    *,
    conversation_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行一轮意图子链，返回最终 state。"""
    result: dict[str, Any] = await graph.ainvoke(
        turn_state(turn, conversation_id=conversation_id), config=config or {}
    )
    return result


__all__ = ["build_intent_graph", "requires_replay", "run_turn", "turn_state"]
