"""render 节点：从 final state 生成 reply_text（Issue #20 M2 实现）。

业务卡片由 Java 生成；api_result 保留原文，展示按 Dify 的业务码规则投影。
本地只生成纠错、消歧、缺上下文及执行结果待核对提示。
"""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.observability.metrics import emit_fallback, emit_hitl
from app.tools.receipts import SERVICE_UNAVAILABLE, UNCERTAIN_REPLY, receipt_text

# ============================================================
# 话术常量
# ============================================================

_HITL_HEADER = "以下标的均可能匹配，请确认选择哪个："
_ZERO_HIT_TMPL = (
    "抱歉，无法识别「{raw_text}」中的标的，"
    "能换一种更标准的说法吗？"
    "（例如：证券代码如 600519.SH，或完整名称如 贵州茅台）"
)
# DSL v2 env.default_reply 等价物:统一兜底文案从配置读(现场可改不发版)
_ERROR_REPLY = get_settings().default_reply
_UNREACHABLE_REPLY = SERVICE_UNAVAILABLE
_OPTION_MISSING_CONTEXT_REPLY = (
    "请求信息不完整，暂时无法调用期权服务，请重新发送原消息或联系运营。"
)
_OPTION_NO_RESULT_REPLY = UNCERTAIN_REPLY
_SWAP_MISSING_CONTEXT_REPLY = (
    "请求信息不完整，暂时无法调用互换服务，请重新发送原消息或联系运营。"
)
_SWAP_NO_RESULT_REPLY = UNCERTAIN_REPLY


def _format_hitl_card(hitl_candidates: list[dict[str, Any]]) -> str:
    """把 hitl_pending 列表格式化成文本消歧卡片。"""
    lines: list[str] = []
    for item in hitl_candidates:
        keyword = item.get("keyword", "?")
        candidates = item.get("candidates", [])
        lines.append(f"关于「{keyword}」：")
        for idx, c in enumerate(candidates, 1):
            wind_code = c.get("windCode", "")
            sht_desc = c.get("insShtDesc") or wind_code
            lines.append(f"  {idx}. {sht_desc}（{wind_code}）")
    if not lines:
        return _ERROR_REPLY
    return _HITL_HEADER + "\n" + "\n".join(lines)


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

    # HITL 消歧
    hitl = state.get("ticker_hitl_candidates")
    if hitl:
        emit_hitl(node="render")
        emit_fallback(reason="hitl_card")
        return {"reply_text": _format_hitl_card(hitl)}, "hitl_card"


    # 4. 0 命中（标的为空且无有效订单参数）
    tickers = state.get("tickers")
    place_params = state.get("place_params")
    if tickers is not None and len(tickers) == 0 and bool(place_params):
        emit_fallback(reason="zero_match")
        raw_text = (state.get("raw_text") or "")[:40]
        return {"reply_text": _ZERO_HIT_TMPL.format(raw_text=raw_text)}, "zero_match"


    # error → 区分不可达 vs 一般 cascade fail
    if err is not None:
        if err_type == "BackendUnreachableError":
            emit_fallback(reason="backend_unreachable")
            return {"reply_text": _UNREACHABLE_REPLY}, "error:backend_unreachable"
        emit_fallback(reason="cascade_fail")
        return {"reply_text": _ERROR_REPLY}, "error:cascade_fail"

    if product_type == "unknown" or state.get("intent") == "unknown_intent":
        return {"reply_text": _ERROR_REPLY}, "unknown_intent"

    intent = state.get("intent") or ""
    if product_type in ("option", "option_close", "swap") and intent:
        return {"reply_text": UNCERTAIN_REPLY}, "backend_no_result"
    return {"reply_text": _ERROR_REPLY}, "no_reply"
