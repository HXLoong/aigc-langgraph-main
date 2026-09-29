"""close 请求边界：准备原值 → 独立清洗 → 一次 Java 调用。"""
from __future__ import annotations

from typing import Any, cast

from app.extraction.fields import merge_fields
from app.extraction.identity import protect_identity_lists
from app.extraction.locks import protect_orders
from app.graph.retry import io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.subgraphs.request_boundary import (
    clean_pending_request,
    send_cleaned_request,
    stage_request,
)
from app.tools.option_client import OptionClientHttpx, OptionIntentionType


async def prepare_close_request(state: AgentState, *, intent: str, close_order_req_vo: dict[str, Any]) -> dict[str, Any]:
    """保护本次身份与字段，只准备请求；没有 HTTP 副作用。"""
    OptionIntentionType(intent)
    payload, identity_rejected = protect_identity_lists(state, close_order_req_vo)
    orders, rejected = protect_orders(state, payload.get("closeOrderList") or [], product="close")
    if "closeOrderList" in payload:
        payload["closeOrderList"] = orders
    rejected = {**rejected, **identity_rejected}
    update = stage_request(state, "close", payload, intent)
    return {**update, **({"field_records": rejected} if rejected else {})}


@safe_node
async def close_clean_request(state: AgentState) -> dict[str, Any]:
    """清洗独立出站副本，保留原参数与完整省略/转换记录。"""
    return clean_pending_request(state, "close")


@safe_node
async def close_submit(state: AgentState) -> dict[str, Any]:
    """提交写请求及 Dify JSON 回退请求，不自动重试。"""
    return await send_cleaned_request(state, "close", OptionClientHttpx())


@io_node
async def close_query_backend(state: AgentState) -> dict[str, Any]:
    """独立只读 HTTP 查询可重试，不包含模型或清洗阶段。"""
    return await send_cleaned_request(state, "close", OptionClientHttpx())


async def call_close_backend(state: AgentState, *, intent: str, close_order_req_vo: dict[str, Any]) -> dict[str, Any]:
    """直接边界调用复用图中的同一准备/清洗/提交实现，便于独立联调。"""
    prepared = await prepare_close_request(state, intent=intent, close_order_req_vo=close_order_req_vo)
    current = cast(AgentState, {**state, **prepared,
        "field_records": merge_fields(state.get("field_records"), prepared.get("field_records"))})
    cleaned = clean_pending_request(current, "close")
    result = await send_cleaned_request(cast(AgentState, {**current, **cleaned}), "close", OptionClientHttpx())
    return {**prepared, **cleaned, **result}
