"""swap 请求边界：准备原值 → 独立清洗 → 一次 Java 调用。"""
from __future__ import annotations

from typing import Any, cast

from app.extraction.fields import merge_fields
from app.extraction.locks import protect_orders
from app.graph.retry import io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.subgraphs.request_boundary import (
    clean_pending_request,
    send_cleaned_request,
    stage_request,
)
from app.tools.swap_client import SwapClientHttpx, SwapIntentionType


async def prepare_swap_request(state: AgentState, *, intent: str, order_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """保护本次身份与字段，只准备请求；没有 HTTP 副作用。"""
    orders, rejected = protect_orders(state, order_list or [], product="swap")
    payload: dict[str, Any] = {"type": SwapIntentionType(intent).value, "orderList": orders}
    update = stage_request(state, "swap", payload, intent)
    return {**update, **({"field_records": rejected} if rejected else {})}


@safe_node
async def swap_clean_request(state: AgentState) -> dict[str, Any]:
    """清洗独立出站副本，保留原参数与完整省略/转换记录。"""
    return clean_pending_request(state, "swap")


@safe_node
async def swap_submit(state: AgentState) -> dict[str, Any]:
    """提交写请求及 Dify JSON 回退请求，不自动重试。"""
    return await send_cleaned_request(state, "swap", SwapClientHttpx())


@io_node
async def swap_query_backend(state: AgentState) -> dict[str, Any]:
    """独立只读 HTTP 查询可重试，不包含模型或清洗阶段。"""
    return await send_cleaned_request(state, "swap", SwapClientHttpx())


async def call_swap_backend(state: AgentState, *, intent: str, order_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """直接边界调用复用图中的同一准备/清洗/提交实现，便于独立联调。"""
    prepared = await prepare_swap_request(state, intent=intent, order_list=order_list)
    current = cast(AgentState, {**state, **prepared,
        "field_records": merge_fields(state.get("field_records"), prepared.get("field_records"))})
    cleaned = clean_pending_request(current, "swap")
    result = await send_cleaned_request(cast(AgentState, {**current, **cleaned}), "swap", SwapClientHttpx())
    return {**prepared, **cleaned, **result}
