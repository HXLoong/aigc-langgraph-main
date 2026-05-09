"""期权平仓子图。

对应 Dify 主工作流的期权平仓节点群（约 10 个节点）：
- 期权平仓-意图识别
- 期权平仓-持仓查询参数提取
- 请求下单和确认全部平仓参数提取
- 确认平仓 / 撤单参数提取 / 确认撤单参数提取 / 平仓订单查询
- 期权平仓-参数聚合
- 期权平仓-统一接口调用（financial-orders/operate）

5 种意图合并为 4 个参数提取节点（确认平仓/撤单/确认撤单逻辑类似，共享一个）。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.nodes.common import safe_node
from app.state import AgentState, preview
from app.subgraphs.close_models import (
    CloseHoldingQueryOutput,
    CloseIntentOutput,
    CloseOrderNoListOutput,
    ClosePlaceOrderOutput,
)
from app.tools.otc_backend import OtcBackendClient

logger = logging.getLogger(__name__)


# ==============================================================
# 意图识别（使用 Dify 原始 13K 字符提示词）
# ==============================================================
@safe_node
async def classify_close_intent(state: AgentState) -> dict[str, Any]:
    """期权平仓意图识别。对应 Dify `期权平仓-意图识别`。"""
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    prompt = load_prompt("option_close", "intent")

    wx = state["wechat_input"]
    user_msg = f"""raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}"""

    llm = get_qwen_standard().with_structured_output(CloseIntentOutput)
    result: CloseIntentOutput = await llm.ainvoke([
        ("system", prompt.system),
        ("user", user_msg),
    ])

    return {
        "intent": result.type,
        "trace": [{"node": "classify_close_intent", "decision": result.type}],
    }


def route_close_intent(state: AgentState) -> str:
    intent = state.get("intent")
    mapping = {
        "close_order_query": "extract_holding_query",
        "close_order_request": "extract_place_close",
        "close_order_confirm": "extract_order_no_list",
        "close_order_cancel": "extract_order_no_list",
        "close_order_confirm_cancel": "extract_order_no_list",
        "close_order_query_status": "extract_order_no_list",
    }
    return mapping.get(intent, "call_close_api")


# ==============================================================
# 持仓查询参数提取
# ==============================================================
# ==============================================================
# 持仓查询参数提取（使用 Dify 原始 12K 字符提示词）
# ==============================================================
@safe_node
async def extract_holding_query(state: AgentState) -> dict[str, Any]:
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    prompt = load_prompt("option_close", "holding_query")

    wx = state["wechat_input"]
    user_msg = f"raw_content: {wx.get('raw_content', '')}"

    llm = get_qwen_standard().with_structured_output(CloseHoldingQueryOutput)
    result: CloseHoldingQueryOutput = await llm.ainvoke([
        ("system", prompt.system),
        ("user", user_msg),
    ])

    return {
        "order_list": [result.model_dump(exclude_none=True)],
        "trace": [{"node": "extract_holding_query",
                   "output_preview": preview(result.model_dump())}],
    }


# ==============================================================
# 请求平仓参数提取（使用 Dify 原始 50K+ 字符提示词）
#
# 最新 Dify 版本（2026-05）的关键变化：
# 1. 新增 `orderList` 输入（含 availableNotional / contractCode / notional），
#    LLM 用它支持基于比例 / 余量目标的平仓金额计算（平一半 / 平X% / 平剩到Xw）。
# 2. 因此本节点前需要先调 /admin-api/financial-orders/query-close-orders 拉取
#    待平仓订单的实际 availableNotional。
# ==============================================================
def _extract_close_targets(text: str) -> tuple[list[str], list[str]]:
    """从用户文本中粗取 orderId（CO-...） / contractCode（OPT-/OPTG-...）。

    LLM 提示词依赖 orderList，但我们在调 LLM 之前需要知道要拉哪些订单的明细，
    因此先用正则拿到候选 ID。漏拣不影响主流程（mock 后端会按 orderId 兜底）。
    """
    import re

    order_ids = re.findall(r"\bCO-\d{8}-[A-Z0-9]{8,12}\b", text or "")
    contract_codes = re.findall(r"\b(?:OPT|OPTG)-\d{8}-[A-Z0-9]{4,12}\b", text or "")
    # 去重，保持出现顺序
    return list(dict.fromkeys(order_ids)), list(dict.fromkeys(contract_codes))


@safe_node
async def extract_place_close(state: AgentState) -> dict[str, Any]:
    from app.llm.clients import get_qwen_thinking
    from app.prompts import load_prompt

    prompt = load_prompt("option_close", "place_close")

    wx = state["wechat_input"]
    raw = wx.get("raw_content", "") or ""
    quote = wx.get("quote_content", "") or ""

    # 拉 orderList（含 availableNotional），失败时降级为空列表
    order_ids, contract_codes = _extract_close_targets(raw + "\n" + quote)
    order_list_for_llm: list[dict[str, Any]] = []
    if order_ids or contract_codes:
        async with OtcBackendClient() as client:
            order_list_for_llm = await client.query_close_orders(
                order_ids=order_ids,
                contract_codes=contract_codes,
                room_id=wx.get("room_id", ""),
                message_id=wx.get("message_id", ""),
            )

    import json as _json
    order_list_str = _json.dumps(order_list_for_llm, ensure_ascii=False)
    user_msg = f"""User input: {raw}
quote_content: {quote or '(无)'}
orderList: {order_list_str}"""

    llm = get_qwen_thinking().with_structured_output(ClosePlaceOrderOutput)
    try:
        result: ClosePlaceOrderOutput = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_msg),
        ])
    except Exception as e:
        return {
            "error": f"平仓参数解析失败: {e}",
            "trace": [{"node": "extract_place_close", "status": "error"}],
        }

    order_list = [leg.model_dump(exclude_none=True, by_alias=True)
                  for leg in result.close_order_list]
    return {
        "order_list": order_list,
        "trace": [{
            "node": "extract_place_close",
            "decision": f"orderList_size={len(order_list_for_llm)}",
            "output_preview": preview(order_list),
        }],
    }


# ==============================================================
# 订单号列表提取（按意图选择 Dify 对应提示词）
# ==============================================================
@safe_node
async def extract_order_no_list(state: AgentState) -> dict[str, Any]:
    """按意图从 Dify 的 confirm_close / cancel_close / confirm_cancel / query_status 选择提示词。"""
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    intent_to_prompt = {
        "close_order_confirm": "confirm_close",
        "close_order_cancel": "cancel_close",
        "close_order_confirm_cancel": "confirm_cancel",
        "close_order_query_status": "query_status",
    }
    intent = state.get("intent", "")
    prompt_name = intent_to_prompt.get(intent, "confirm_close")
    prompt = load_prompt("option_close", prompt_name)

    wx = state["wechat_input"]
    user_msg = f"""raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}"""

    llm = get_qwen_standard().with_structured_output(CloseOrderNoListOutput)
    try:
        result: CloseOrderNoListOutput = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_msg),
        ])
    except Exception as e:
        return {
            "error": f"订单号列表提取失败: {e}",
            "trace": [{"node": "extract_order_no_list", "status": "error"}],
        }

    if not result.order_no_list:
        return {
            "error": "未能从输入中识别出订单号",
            "trace": [{"node": "extract_order_no_list", "decision": "not_found"}],
        }

    return {
        "order_ids": result.order_no_list,
        "order_list": [{"orderNo": no} for no in result.order_no_list],
        "trace": [{"node": "extract_order_no_list",
                   "decision": f"prompt={prompt_name}",
                   "output_preview": ",".join(result.order_no_list)}],
    }


# ==============================================================
# 调用统一接口
# ==============================================================
@safe_node
async def call_close_api(state: AgentState) -> dict[str, Any]:
    """调用 /admin-api/financial-orders/operate。对应 Dify `期权平仓-统一接口调用`。"""
    if state.get("error"):
        return {
            "api_code": 400,
            "api_result": state.get("error"),
            "trace": [{"node": "call_close_api", "status": "skip"}],
        }

    wx = state["wechat_input"]
    intent = state.get("intent", "unknown")
    order_list = state.get("order_list", [])

    payload = {
        "conversationId": wx.get("conversation_id", ""),
        "messageId": wx.get("message_id", ""),
        "rawContent": wx.get("raw_content", ""),
        "quoteContent": wx.get("quote_content"),
        "userId": wx.get("user_id", ""),
        "roomId": wx.get("room_id", ""),
        "guid": wx.get("guid", ""),
        "type": intent,
        "orderList": order_list,
    }

    async with OtcBackendClient() as client:
        resp = await client.financial_orders_operate(**payload)

    return {
        "api_code": resp.get("code"),
        "api_result": resp.get("result"),
        "trace": [{"node": "call_close_api",
                   "output_preview": f"code={resp.get('code')}"}],
    }


# ==============================================================
# 构建子图
# ==============================================================
def build_close_graph():
    """期权平仓子图。

    拓扑：
        START → classify_close_intent
                     │
           ┌─────────┼─────────┬──────────────────┐
           ▼         ▼         ▼                  ▼
     extract_   extract_   extract_         (兜底)
     holding_   place_     order_no_list
     query      close
           │         │         │                  │
           └─────────┴─────────┴──────┬───────────┘
                                      ▼
                               call_close_api
                                      ▼
                                     END
    """
    g = StateGraph(AgentState)

    g.add_node("classify_close_intent", classify_close_intent)
    g.add_node("extract_holding_query", extract_holding_query)
    g.add_node("extract_place_close", extract_place_close)
    g.add_node("extract_order_no_list", extract_order_no_list)
    g.add_node("call_close_api", call_close_api)

    g.add_edge(START, "classify_close_intent")
    g.add_conditional_edges(
        "classify_close_intent",
        route_close_intent,
        {
            "extract_holding_query": "extract_holding_query",
            "extract_place_close": "extract_place_close",
            "extract_order_no_list": "extract_order_no_list",
            "call_close_api": "call_close_api",
        },
    )
    g.add_edge("extract_holding_query", "call_close_api")
    g.add_edge("extract_place_close", "call_close_api")
    g.add_edge("extract_order_no_list", "call_close_api")
    g.add_edge("call_close_api", END)

    return g
