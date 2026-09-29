"""三个产品共用的请求准备、清洗和提交投影，不承担业务默认值。"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter

from app.domain.request_cleaning import clean_business_request
from app.extraction.fields import EvidenceError
from app.extraction.identity import protect_identity_lists
from app.extraction.locks import protect_orders
from app.graph.state import AgentState, TraceEntry
from app.observability.metrics import (
    emit_option_backend_empty_result,
    emit_option_backend_missing_context,
)
from app.tools.bot_context import BotContext
from app.tools.exceptions import (
    BackendUnreachableError,
    EmptyBackendResultError,
    MissingBackendContextError,
)
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO
from app.tools.receipts import SERVICE_UNAVAILABLE, receipt_guard, receipt_update
from app.tools.swap_client import SwapOrderOpenApiSaveReqVO

_PAYLOAD = TypeAdapter(dict[str, Any])


def stage_request(state: AgentState, product: str, payload: dict[str, Any] | str,
                  intent: str | None) -> dict[str, Any]:
    """参数准备只检查调用身份并保存原请求，图中的后续节点负责清洗与提交。"""
    missing = BotContext.from_state(state).missing_required()
    if missing:
        logging.getLogger(f"app.subgraphs.{product}.backend").error(
            "%s backend call blocked: missing_fields=%s", product, ",".join(missing),
        )
        if product == "option":
            emit_option_backend_missing_context()
        raise MissingBackendContextError(product, missing)
    return {"pending_backend_request": {"product": product, "payload": deepcopy(payload), "intent": intent}}


def clean_pending_request(state: AgentState, product: str) -> dict[str, Any]:
    """从原请求生成独立出站副本；原参数和字段账本均不改写。"""
    pending = state.get("pending_backend_request")
    if not pending or pending["product"] != product:
        raise ValueError("缺少当前产品的待清洗请求")
    try:
        cleaned = clean_business_request(product, pending["payload"], intent=pending.get("intent"))
    except ValueError as exc:
        raise EvidenceError(str(exc)) from exc
    # 独立节点回放也检查清洗前的原值；检查完不把原账本覆盖到出站副本。
    # Dify JSON 失败没有可恢复的订单，按明确约定继续发送空对象。
    if not cleaned.json_fallback:
        key = "closeOrderList" if product == "close" else "orderList"
        _, rejected = protect_orders(state, cleaned.original.get(key) or [], product=product)
        if product == "close":
            _, identity_rejected = protect_identity_lists(state, cleaned.original)
            rejected = {**rejected, **identity_rejected}
        if rejected:
            raise EvidenceError("待清洗请求与锁定字段不一致")
    return {
        # Decimal 在节点 HTTP 往返前固定成 Java 支持的数字字符串，避免浮点精度损失。
        "cleaned_backend_request": {"product": product, "payload": _PAYLOAD.dump_python(cleaned.payload, mode="json"), "json_fallback": cleaned.json_fallback},
        "cleaning_records": cleaned.changes,
        "trace": [TraceEntry(node=f"{product}_clean_request", decision=f"changes={len(cleaned.changes)},json_fallback={cleaned.json_fallback}",
                             llm_output={"cleaning_records": cleaned.changes})],
    }


def _submitted_params(state: AgentState, payload: dict[str, Any], product: str) -> dict[str, Any]:
    """用实际请求投影既有参数信封，避免评测断言原始而未提交的值。"""
    projected: dict[str, Any] = {}
    for key in ("place_params", "cancel_params", "confirm", "query_filter", "close_params"):
        original = state.get(key)
        if not isinstance(original, dict):
            continue
        if product == "close":
            params = payload.get("closeOrderReqVO") or {}
            # 持仓查询原输出使用模型字段名，保留该外部形状并取实际发送值。
            if "contractQuery" in params and key == "close_params":
                value = dict(params["contractQuery"])
                if "allowCloseOut" in value:
                    value["closeable_only"] = value.pop("allowCloseOut") == "true"
            else:
                value = {**original, **params}
        else:
            value = {**original, "orderList": payload.get("orderList", [])}
        projected[key] = value
    return projected


async def send_cleaned_request(state: AgentState, product: str, client: Any) -> dict[str, Any]:
    """装配真实 DTO 后发送一次；清洗之后不再从原值账本回填字段。"""
    # 1. 单节点执行同样核对清洗结果，不能把任意字典冒充已清洗请求。
    cleaned = state.get("cleaned_backend_request")
    expected = clean_pending_request(state, product)["cleaned_backend_request"]
    if cleaned is None or cleaned != expected:
        raise EvidenceError("提交参数与本次清洗结果不一致")
    missing = BotContext.from_state(state).missing_required()
    if missing:
        raise MissingBackendContextError(product, missing)
    body = {**cleaned["payload"], **BotContext.from_state(state).to_wire()}
    if product == "swap":
        body["operatorUserId"] = body.get("operatorUserId") or ""
    model = SwapOrderOpenApiSaveReqVO if product == "swap" else FinancialOrderOpenApiSaveReqVO
    request = model.model_validate(body)
    wire = request.model_dump(mode="json", exclude_none=True)
    update: dict[str, Any] = {"backend_request": wire, "submitted_params": _submitted_params(state, wire, product)}
    # 2. 只有字符串 JSON 回退路径沿用 Dify HTTP 错误展示，其它错误保持原异常契约。
    try:
        async with receipt_guard(product):
            result = await client.operate(request)
    except BackendUnreachableError as exc:
        if not cleaned["json_fallback"]:
            raise
        cause = exc.__cause__ or exc
        response = getattr(cause, "response", None)
        detail = {"error_type": type(cause).__name__, "message": str(cause),
                  "http_status": response.status_code if response is not None else None,
                  "response": response.text if response is not None else None}
        return {**update, "api_code": 500, "api_result": response.text if response is not None else str(cause), "reply_text": SERVICE_UNAVAILABLE,
                "trace": [TraceEntry(node=f"{product}_submit", decision="dify_json_fallback_http_error", llm_output=detail)]}
    try:
        receipt = receipt_update(result, product)
    except EmptyBackendResultError:
        if product == "option":
            emit_option_backend_empty_result()
        raise
    return {**update, **receipt}


def after_prepare(state: AgentState) -> str:
    """准备失败或已有回复时结束；成功请求才能进入清洗。"""
    return "done" if state.get("error") or state.get("reply_text") or not state.get("pending_backend_request") else "clean"


def after_clean(state: AgentState) -> str:
    """只读查询独立可重试，任何写入和 JSON 回退均不自动重试。"""
    request = state.get("cleaned_backend_request")
    if state.get("error") or not request:
        return "done"
    intent = request["payload"].get("type")
    return "query" if not request["json_fallback"] and intent in {"query_order_status", "close_order_query", "close_order_order_query"} else "submit"
