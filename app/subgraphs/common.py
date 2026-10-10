"""三个业务子图共用的图骨架：意图节点后的分发路由与 unknown 兜底节点。

每个子图都是「intent → 按意图分发到一个业务节点 → END」，意图未知或上游节点写入
state['error'] 时落到本子图的 `<product>_unknown`（CLAUDE.md 核心原则第 9 条）。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from langgraph.graph import StateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry


class StateNode(Protocol):
    """LangGraph 节点签名（参数名须为 state）。"""

    def __call__(self, state: AgentState) -> Awaitable[dict[str, Any]]: ...


def make_unknown_node(name: str) -> StateNode:
    """生成 unknown_intent / cascade 错误兜底节点：只记录未处理的意图，回复交给主图 render。"""

    async def unknown(state: AgentState) -> dict[str, Any]:
        intent = state.get("intent") or "unknown_intent"
        return {"trace": [TraceEntry(node=name, decision=f"unhandled_intent={intent}")]}

    # safe_node 以函数名作为 trace / 错误里的节点名
    unknown.__name__ = unknown.__qualname__ = name
    return safe_node(unknown)


def intent_router(
    intent_to_node: Mapping[str, str], fallback: str,
) -> Callable[[AgentState], str]:
    """意图节点后的纯函数路由：error 优先落兜底，其余按意图表分发，未登记意图落兜底。"""

    def route(state: AgentState) -> str:
        if has_error(state):
            return fallback
        return intent_to_node.get(state.get("intent") or "unknown_intent", fallback)

    return route


def add_intent_dispatch(
    g: StateGraph[Any, Any, Any, Any],
    source: str,
    router: Callable[[AgentState], str],
    intent_to_node: Mapping[str, str],
    fallback: str,
) -> list[str]:
    """注册意图分发条件边；返回全部目标节点（含兜底，按首次出现顺序），供调用方接 END。"""
    targets = list(dict.fromkeys([*intent_to_node.values(), fallback]))
    g.add_conditional_edges(source, router, {target: target for target in targets})
    return targets


__all__ = ["StateNode", "add_intent_dispatch", "intent_router", "make_unknown_node"]
