"""候选去重后一次模型过滤排序；不调用证券查询或执行交易。"""

from __future__ import annotations

import json
import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import ErrorInfo, TraceEntry
from app.parsing.tool_workflow import invoke_tool_model, merge_tool_errors, parse_list
from app.prompts.spec import PromptSpec
from instrument_ranking.models import RankedCodes


class RankingState(TypedDict, total=False):
    raw_list: str
    keyword: str
    predicted_family: str
    expected_transaction_type: str
    candidates: list[dict[str, Any]]
    current_date: str
    error: Annotated[ErrorInfo | None, merge_tool_errors]
    trace: Annotated[list[TraceEntry], operator.add]
    trace_id: str
    outputs: dict[str, Any]


def _user(state: RankingState) -> str:
    return json.dumps(
        {
            "keyword": state["keyword"],
            "predictedInsFamily": state.get("predicted_family", ""),
            "expectedTransactionType": state.get("expected_transaction_type", ""),
            "list": state["candidates"],
        },
        ensure_ascii=False,
    )


RANK_SPEC = PromptSpec(
    category="instrument",
    name="rank_candidates",
    output_model=RankedCodes,
    inputs=(
        "keyword",
        "predicted_family",
        "expected_transaction_type",
        "candidates",
        "current_date",
    ),
    state_schema=RankingState,
    user_builder=_user,
    injects={"{{current_date}}": lambda s: s["current_date"]},
)


@safe_node
async def parse_candidates(state: RankingState) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parse_list(state["raw_list"]):
        if not isinstance(item, dict):
            continue
        code = item.get("windCode")
        if not isinstance(code, str) or not code or code in seen:
            continue
        seen.add(code)
        candidates.append(item)
    return {
        "candidates": candidates,
        "outputs": {"result": "[]"},
        "current_date": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y/%m/%d %H:%M:%S"),
    }


@safe_node
async def rank_candidates(state: RankingState, config: RunnableConfig) -> dict[str, Any]:
    result = await invoke_tool_model(RANK_SPEC, state, RankedCodes, config)
    allowed = {item["windCode"] for item in state["candidates"]}
    if any(code not in allowed for code in result.result):
        raise ValueError("排序结果包含候选列表之外的代码")
    if len(set(result.result)) != len(result.result):
        raise ValueError("排序结果包含重复代码")
    return {"outputs": {"result": result.result}}


def _after_parse(state: RankingState) -> str:
    return END if state.get("error") or not state.get("candidates") else "rank_candidates"


def build_graph() -> CompiledStateGraph[RankingState, None, RankingState, RankingState]:
    graph = StateGraph(RankingState)
    graph.add_node("parse_candidates", parse_candidates)
    graph.add_node("rank_candidates", rank_candidates)
    graph.add_edge(START, "parse_candidates")
    graph.add_conditional_edges("parse_candidates", _after_parse)
    graph.add_edge("rank_candidates", END)
    return graph.compile()
