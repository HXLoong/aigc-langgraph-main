"""子图契约守护（ADR 0024 D2/D3）。"""
from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from app.graph.main import build_main_graph
from app.subgraphs.close import build_close_graph
from app.subgraphs.option import build_option_graph
from app.subgraphs.swap import build_swap_graph

#: 父图路由键与入口字段：子图只读，不得出现在子图 output_schema
_PARENT_OWNED = {"product_type", "swap_input_mode", "history_messages", "raw_text", "conversation_id"}
#: 子图对父图的合法写回面
_SUBGRAPH_OWNED = {"intent", "trace", "error", "place_params", "reply_text", "api_result", "api_code"}


def test_business_subgraphs_are_embedded_natively() -> None:
    """不再用 _as_subgraph_node 手写 ainvoke + Overwrite 包装。"""
    graph = build_main_graph()
    for name in ("swap", "option", "option_close"):
        assert isinstance(graph.nodes[name].bound, CompiledStateGraph), name


def test_business_subgraphs_declare_output_schema() -> None:
    for build in (build_swap_graph, build_option_graph, build_close_graph):
        out = set(build().output_channels)
        assert not (out & _PARENT_OWNED), (build.__name__, out & _PARENT_OWNED)
        assert out >= _SUBGRAPH_OWNED, (build.__name__, _SUBGRAPH_OWNED - out)


def test_turn_boundary_lives_in_ingest_only() -> None:
    """ADR 0024 D2：删除 _reset_turn_trace，一轮的边界只在 ingest 维护。"""
    graph = build_main_graph()
    assert "reset_turn_trace" not in graph.nodes
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("__start__", "ingest") in edges


def test_langfuse_injection_is_request_level_only() -> None:
    """ADR 0024 D5：删除图级 _attach_langfuse_callbacks 与 environment 分叉，
    所有环境统一走 routes.attach_request_trace 的请求级 handler。"""
    import inspect

    import app.graph.main as graph_main

    assert not hasattr(graph_main, "_attach_langfuse_callbacks")
    assert "attach_langfuse_callbacks" not in inspect.signature(graph_main.build_main_graph).parameters
    assert isinstance(graph_main.build_main_graph(), CompiledStateGraph)


async def test_subgraph_cannot_rewrite_parent_routing_key_at_runtime(monkeypatch) -> None:
    """运行级守护：子图节点即使写了 product_type，经 output_schema 过滤后父图值不变。"""
    from langgraph.graph import END, START, StateGraph

    from app.graph.retry import io_node
    from app.graph.state import AgentState
    from app.subgraphs.swap import graph as swap_graph_module

    @io_node
    async def rogue_intent(state):
        return {"intent": "unknown_intent", "product_type": "option", "raw_text": "改写入口"}

    monkeypatch.setattr(swap_graph_module, "swap_intent", rogue_intent)
    parent: StateGraph = StateGraph(AgentState)
    parent.add_node("swap", swap_graph_module.build_swap_graph())
    parent.add_edge(START, "swap")
    parent.add_edge("swap", END)
    final = await parent.compile().ainvoke({"product_type": "swap", "raw_text": "原文"})

    assert final["product_type"] == "swap"
    assert final["raw_text"] == "原文"
    assert final["intent"] == "unknown_intent"  # 合法写回面照常生效
