"""option 请求边界：准备原值 → 独立清洗 → 一次 Java 调用。"""
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
from app.tools.option_client import OptionClientHttpx, OptionIntentionType

_INTENT_TO_OPERATE: dict[str, str] = {
    "new_inquiry": "询价",
    "place_order_from_quote": "交易",
    "confirm_order": "交易",
    "cancel_order_request": "取消",
    "request_cancel_order": "交易",
    "confirm_cancel_order": "交易",
    "query_order_status": "交易",
}


async def prepare_option_request(state: AgentState, *, intent: str, order_list: list[dict[str, Any]] | None = None, option_rfq: dict[str, Any] | None = None) -> dict[str, Any]:
    """保护本次身份与字段，只准备请求；没有 HTTP 副作用。"""
    orders, rejected = protect_orders(state, order_list or [], product="option")
    payload: dict[str, Any] = {"type": OptionIntentionType(intent).value,
                               "operate": _INTENT_TO_OPERATE.get(intent), "orderList": orders}
    if option_rfq is not None:
        payload["optionRfq"] = option_rfq
    update = stage_request(state, "option", payload, intent)
    return {**update, **({"field_records": rejected} if rejected else {})}


@safe_node
async def option_clean_request(state: AgentState) -> dict[str, Any]:
    """清洗独立出站副本，保留原参数与完整省略/转换记录。"""
    return clean_pending_request(state, "option")


@safe_node
async def option_submit(state: AgentState) -> dict[str, Any]:
    """提交写请求及 Dify JSON 回退请求，不自动重试。"""
    return await send_cleaned_request(state, "option", OptionClientHttpx())


@io_node
async def option_query_backend(state: AgentState) -> dict[str, Any]:
    """独立只读 HTTP 查询可重试，不包含模型或清洗阶段。"""
    return await send_cleaned_request(state, "option", OptionClientHttpx())


async def call_option_backend(state: AgentState, *, intent: str, order_list: list[dict[str, Any]] | None = None, option_rfq: dict[str, Any] | None = None) -> dict[str, Any]:
    """直接边界调用复用图中的同一准备/清洗/提交实现，便于独立联调。"""
    prepared = await prepare_option_request(state, intent=intent, order_list=order_list, option_rfq=option_rfq)
    current = cast(AgentState, {**state, **prepared,
        "field_records": merge_fields(state.get("field_records"), prepared.get("field_records"))})
    cleaned = clean_pending_request(current, "option")
    result = await send_cleaned_request(cast(AgentState, {**current, **cleaned}), "option", OptionClientHttpx())
    return {**prepared, **cleaned, **result}
