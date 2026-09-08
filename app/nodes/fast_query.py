"""快速询价与存量兼容前置分支(DSL v2 主干前置链)。

对照源:主干工作流「判断快速询价」if-else 及其两条分支:
- fast_query == "1" → 「参与型看涨、雪球调询价参数解析」→「期权快速询价」
- existing_command == "1" 且 at_bot == "0" → 「存量兼容-交易查询指令」

两分支不进一级路由,结果直接落 reply_text / api_result / api_code。
存量兼容分支恒回 IGNORE_REQUEST_NOT_REPLY_USER 哨兵(Java 机器人层静默)。
"""
from __future__ import annotations

import json
from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.tools.goats_agent_client import make_goats_agent_client
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO

_SERVICE_UNAVAILABLE = "交易指令服务暂不可用"


def _make_agent_client():
    """工厂间接层(测试 patch 此名)。"""
    return make_goats_agent_client()


def _make_option_client():
    """工厂间接层(测试 patch 此名)。"""
    from app.tools.option_client import OptionClientHttpx

    return OptionClientHttpx()


def is_fast_query(state: AgentState) -> bool:
    """判断快速询价分支(DSL:fast_query is "1")。"""
    return str(state.get("fast_query") or "") == "1"


def is_existing_command(state: AgentState) -> bool:
    """存量兼容分支(DSL:existing_command is "1" and at_bot is "0")。"""
    at_bot = state.get("at_bot")
    at_bot_str = "0" if at_bot in (False, 0, "0") else "1" if at_bot in (True, 1, "1") else str(at_bot or "")
    return str(state.get("existing_command") or "") == "1" and at_bot_str == "0"


@safe_node
async def quick_inquiry(state: AgentState) -> dict[str, Any]:
    """参与型看涨/雪球快速询价:GOATS 指令解析 → OTC financial-orders/operate。

    payload 组装 1:1 对照「期权快速询价」code 节点(type=new_inquiry /
    operate=询价 为 DSL 存量分支硬编码,语义存疑但如实照搬)。
    """
    query = state.get("raw_text", "") or ""
    room_id = state.get("room_id") or ""
    user_id = state.get("operator_user_id") or state.get("user_id")

    rfq = await _make_agent_client().parse_rfq_instrument(query, room_id, user_id)
    if rfq.get("errMsg"):
        return {
            "api_code": 500,
            "api_result": rfq["errMsg"],
            "reply_text": rfq["errMsg"],
            "trace": [TraceEntry(node="quick_inquiry", decision="rfq_parser_error")],
        }

    option_rfq = rfq.get("api_data_result_obj") or {}
    req = FinancialOrderOpenApiSaveReqVO.model_validate(
        {
            "conversationId": state.get("conversation_id") or "",
            "messageId": int(state.get("message_id") or 0),
            "messageContent": query,
            "quoteAppinfo": state.get("quote_appinfo"),
            "roomId": room_id,
            "guid": state.get("guid"),
            "userId": user_id or "",
            "type": "new_inquiry",
            "operate": "询价",
            "orderList": [],
            "optionRfq": option_rfq,
            "rawContent": query,
            "quoteContent": state.get("quote_content"),
        }
    )
    result = await _make_option_client().operate(req)
    code = getattr(result, "code", None)
    if code == 0:
        reply = getattr(result, "data", "") or ""
    elif code == 500:
        reply = _SERVICE_UNAVAILABLE
    else:
        reply = getattr(result, "msg", None) or "未知错误"
    return {
        "api_code": code,
        "api_result": str(reply),
        "reply_text": str(reply),
        "trace": [TraceEntry(node="quick_inquiry", decision=f"code={code}")],
    }


@safe_node
async def existing_command_query(state: AgentState) -> dict[str, Any]:
    """存量兼容交易查询:GOATS instruction/query;恒回静默哨兵。"""
    query = state.get("raw_text", "") or ""
    room_id = state.get("room_id") or ""
    user_id = state.get("operator_user_id") or state.get("user_id")

    out = await _make_agent_client().query_instruction(query, room_id, user_id)
    obj = out.get("api_data_result_obj")
    return {
        "api_code": out.get("code"),
        "api_result": json.dumps(obj, ensure_ascii=False) if obj is not None else "",
        "reply_text": out.get("errMsg"),  # IGNORE_REQUEST_NOT_REPLY_USER
        "trace": [
            TraceEntry(node="existing_command_query", decision=f"code={out.get('code')}")
        ],
    }


__all__ = [
    "quick_inquiry",
    "existing_command_query",
    "is_fast_query",
    "is_existing_command",
]
