"""主图（Main Graph）组装。

拓扑：
    START → ingest → route_product
                        ├─ option       → option_subgraph  ─┐
                        ├─ swap         → swap_subgraph    ─┤
                        ├─ option_close → close_subgraph   ─┤
                        └─ unknown      → render_reply     ─┤
                                                             ▼
                                                        persist_intent
                                                             ▼
                                                        render_reply
                                                             ▼
                                                            END
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from app.nodes.ingest import ingest
from app.nodes.persist import persist_intent
from app.nodes.render import render_reply
from app.nodes.route import route_product, route_product_condition
from app.state import AgentState
from app.subgraphs.close import build_close_graph
from app.subgraphs.option import build_option_graph
from app.subgraphs.swap import build_swap_graph

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


def build_main_graph(checkpointer: BaseCheckpointSaver | None = None):
    """构建并编译主图。

    Args:
        checkpointer: 任何实现了 BaseCheckpointSaver 协议的对象
                      （AIOMySQLSaver / InMemorySaver / SqliteSaver 等）
    """
    g = StateGraph(AgentState)

    # 顶层节点
    g.add_node("ingest", ingest)
    g.add_node("route_product", route_product)
    g.add_node("persist_intent", persist_intent)
    g.add_node("render_reply", render_reply)

    # 子图（作为节点嵌入）
    g.add_node("option", build_option_graph().compile())
    g.add_node("swap", build_swap_graph().compile())
    g.add_node("close", build_close_graph().compile())

    # 主干
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "route_product")

    # 条件路由
    g.add_conditional_edges(
        "route_product",
        route_product_condition,
        {
            "option": "option",
            "swap": "swap",
            "option_close": "close",
            "unknown": "render_reply",   # 未识别直接走兜底回复
        },
    )

    # 所有子图完成后走统一后处理
    for sg_name in ("option", "swap", "close"):
        g.add_edge(sg_name, "persist_intent")

    g.add_edge("persist_intent", "render_reply")
    g.add_edge("render_reply", END)

    compiled = g.compile(checkpointer=checkpointer)
    logger.info("主图编译完成")
    return compiled
