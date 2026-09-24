"""render 节点：从 final state 生成 reply_text。

业务卡片由 Java 生成；api_result 保留原文，展示按 Dify 的业务码规则投影。
本地只生成纠错、消歧、缺上下文及执行结果待核对提示。
"""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.observability.metrics import emit_fallback
from app.tools.receipts import SERVICE_UNAVAILABLE, UNCERTAIN_REPLY, receipt_text

# ============================================================
# 话术常量
# ============================================================

_UNREACHABLE_REPLY = SERVICE_UNAVAILABLE
_OPTION_MISSING_CONTEXT_REPLY = (
    "请求信息不完整，暂时无法调用期权服务，请重新发送原消息或联系运营。"
)
_OPTION_NO_RESULT_REPLY = UNCERTAIN_REPLY
_SWAP_MISSING_CONTEXT_REPLY = (
    "请求信息不完整，暂时无法调用互换服务，请重新发送原消息或联系运营。"
)
_SWAP_NO_RESULT_REPLY = UNCERTAIN_REPLY
_SWAP_NON_POSITIVE_QUANTITY_REPLY = "委托数量必须大于零，请核对后重新发送。"


def _default_reply() -> str:
    """统一兜底文案从配置读（现场可改不发版）；调用期求值，模块 import 不依赖 Settings。"""
    return get_settings().default_reply


@safe_node
async def render(state: AgentState) -> dict[str, Any]:
    """渲染回复；每个分支在 trace 里留下 decision（ADR 0024 D3：决策树可观测）。"""
    update, decision = _render_branch(state)
    return {**update, "trace": [TraceEntry(node="render", decision=decision)]}


def _render_branch(state: AgentState) -> tuple[dict[str, Any], str]:
    """保留节点纠错/静默回复，展示 Java 回执，最后处理异常及交互提示。"""
    # 1. 子图已生成 reply_text → 透传
    if state.get("reply_text"):
        return {}, "passthrough"

    product_type = state.get("product_type")
    api_result = state.get("api_result")
    is_option = product_type in ("option", "option_close")

    # 业务结果优先；code=500 仅改变展示文本，api_result 保留原文。
    if api_result is not None or state.get("api_code") is not None:
        return {"reply_text": receipt_text(state.get("api_code"), api_result)}, "api_result"

    err = state.get("error")
    err_type = None
    if err is not None:
        err_type = err.type if hasattr(err, "type") else (
            err.get("type") if isinstance(err, dict) else None
        )
    if product_type == "swap" and err_type == "NonPositiveQuantityError":
        emit_fallback(reason="swap_non_positive_quantity")
        return {"reply_text": _SWAP_NON_POSITIVE_QUANTITY_REPLY}, "error:swap_non_positive_quantity"
    if is_option and err_type == "MissingBackendContextError":
        emit_fallback(reason="option_backend_missing_context")
        return {"reply_text": _OPTION_MISSING_CONTEXT_REPLY}, "error:option_backend_missing_context"
    if is_option and err_type == "EmptyBackendResultError":
        emit_fallback(reason="option_backend_empty_result")
        return {"reply_text": _OPTION_NO_RESULT_REPLY}, "error:option_backend_empty_result"
    if product_type == "swap" and err_type == "MissingBackendContextError":
        emit_fallback(reason="swap_backend_missing_context")
        return {"reply_text": _SWAP_MISSING_CONTEXT_REPLY}, "error:swap_backend_missing_context"
    if product_type == "swap" and err_type == "EmptyBackendResultError":
        emit_fallback(reason="swap_backend_empty_result")
        return {"reply_text": _SWAP_NO_RESULT_REPLY}, "error:swap_backend_empty_result"

    # error → 区分不可达 vs 一般 cascade fail
    if err is not None:
        if err_type == "BackendUnreachableError":
            emit_fallback(reason="backend_unreachable")
            return {"reply_text": _UNREACHABLE_REPLY}, "error:backend_unreachable"
        emit_fallback(reason="cascade_fail")
        return {"reply_text": _default_reply()}, "error:cascade_fail"

    if product_type == "unknown" or state.get("intent") == "unknown_intent":
        return {"reply_text": _default_reply()}, "unknown_intent"

    intent = state.get("intent") or ""
    if product_type in ("option", "option_close", "swap") and intent:
        return {"reply_text": UNCERTAIN_REPLY}, "backend_no_result"
    return {"reply_text": _default_reply()}, "no_reply"
