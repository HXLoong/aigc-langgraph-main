"""期权子图（完整实现）。

对应 Dify：
- 主工作流的 `期权-意图识别、参数提取`、`期权-参数限制检查`
- 主工作流的 `参与型看涨、雪球调询价参数解析`（快速询价）
- `期权工具.yml`（15 节点）

设计要点：
1. 快速询价（参与型/雪球）走旁路直连后端，不过 LLM（Dify 原逻辑）
2. 其他走：参数提取 → 参数限制检查 → 后端 API
3. 支持存量兼容（existing_command）

阶段 3 可进一步拆分为更细粒度的节点（询价/下单/改单/撤单/确认）。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.nodes.common import safe_node
from app.state import AgentState, preview
from app.subgraphs.option_models import (
    OptionExtractOutput,
    OptionParamLimit,
)
from app.tools.otc_backend import OtcBackendClient

logger = logging.getLogger(__name__)


# ==============================================================
# 快速询价识别（不走 LLM，正则判断）
# ==============================================================
QUICK_QUERY_KEYWORDS = ("参与型看涨", "参与型看跌", "雪球")


@safe_node
async def detect_quick_query(state: AgentState) -> dict[str, Any]:
    """判断是否为快速询价（参与型/雪球）。

    对应 Dify `判断快速询价` 节点。
    """
    raw = state["wechat_input"].get("raw_content", "")
    is_quick = any(k in raw for k in QUICK_QUERY_KEYWORDS)
    return {
        "fast_query": is_quick,
        "trace": [{"node": "detect_quick_query",
                   "decision": "quick" if is_quick else "standard"}],
    }


def route_quick_query(state: AgentState) -> str:
    return "yes" if state.get("fast_query", False) else "no"


# ==============================================================
# 快速询价：直连后端（不过 LLM）
# ==============================================================
@safe_node
async def fast_query_api(state: AgentState) -> dict[str, Any]:
    """快速询价直连 goats（对应 Dify `参与型看涨、雪球调询价参数解析`）。

    Dify 用 Python 代码节点直接调后端接口，不过 LLM。
    """
    # 简化：这里直接调 financial_orders_operate 接口，带特殊 type
    wx = state["wechat_input"]
    async with OtcBackendClient() as client:
        resp = await client.financial_orders_operate(
            conversationId=wx.get("conversation_id", ""),
            messageId=wx.get("message_id", ""),
            messageContent=wx.get("raw_content", ""),
            rawContent=wx.get("raw_content", ""),
            quoteContent=wx.get("quote_content"),
            quoteAppinfo=wx.get("quote_appinfo"),
            userId=wx.get("user_id", ""),
            roomId=wx.get("room_id", ""),
            guid=wx.get("guid", ""),
            operate="fast_inquiry",
            type="new_inquiry",
            orderList=[],  # 快速询价由后端解析
        )
    return {
        "api_code": resp.get("code"),
        "api_result": resp.get("result"),
        "intent": "new_inquiry",
        "trace": [{"node": "fast_query_api", "output_preview": preview(resp)}],
    }


# ==============================================================
# 标准路径：意图识别 + 参数提取（Dify 原节点合并，简化为一个 LLM 调用）
# ==============================================================
OPTION_EXTRACT_PROMPT = """你是一个金融交易指令解析引擎，专门处理期权询价/下单/改单/撤单/确认。

## 任务
从用户输入中识别意图并提取完整的订单参数。

## 意图枚举
- new_inquiry: 新询价
- existing_command: 存量指令（引用已有订单的参数）
- place_order: 下单
- modify_order: 改单
- cancel_order: 撤单
- confirm: 确认
- unknown: 兜底

## 输入
- raw_content: 用户原始消息
- quote_content: 引用消息
- history_query_str: 历史对话
- resolved_tickers: 已 goats 验证的标的列表

## 硬约束
1. 标的代码必须来自 resolved_tickers
2. option_type 限定为枚举内的值
3. 若用户未指定 optionType，默认 "欧式看涨"

## 输出
严格 JSON，符合 OptionExtractOutput 结构。
"""


@safe_node
async def extract_option(state: AgentState) -> dict[str, Any]:
    """期权意图识别 + 参数提取（合并 Dify 两个节点）。"""
    from app.llm.clients import get_qwen_thinking

    wx = state["wechat_input"]
    history = state.get("history_messages", [])
    resolved = state.get("resolved_tickers", [])

    history_str = "\n".join(
        f"[{m.get('role')}] {m.get('content', '')[:200]}" for m in history[-10:]
    )
    resolved_str = "\n".join(
        f"- {t.wind_code} ({t.ins_sht_desc})" for t in resolved
    ) or "(空)"

    user_message = f"""raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}
history_query_str: {history_str or '(无)'}
resolved_tickers:
{resolved_str}"""

    llm = get_qwen_thinking().with_structured_output(OptionExtractOutput)
    try:
        result: OptionExtractOutput = await llm.ainvoke([
            ("system", OPTION_EXTRACT_PROMPT),
            ("user", user_message),
        ])
    except Exception as e:
        return {
            "error": f"期权参数解析失败: {e}",
            "trace": [{"node": "extract_option", "status": "error", "error": str(e)}],
        }

    order_dicts = [leg.model_dump(exclude_none=True) for leg in result.order_list]
    return {
        "intent": result.type,
        "order_list": order_dicts,
        "operate": result.operate,
        "trace": [{
            "node": "extract_option",
            "decision": result.type,
            "output_preview": preview(order_dicts),
        }],
    }


# ==============================================================
# 参数限制检查
# ==============================================================
@safe_node
async def check_param_limit(state: AgentState) -> dict[str, Any]:
    """参数组合数量限制检查。

    对应 Dify `期权-参数限制检查`。
    用纯 Python 代替 LLM，速度更快、更准确。
    """
    order_list = state.get("order_list", [])
    if not order_list:
        return {
            "trace": [{"node": "check_param_limit", "status": "skip",
                       "decision": "empty"}],
        }

    stocks = {o.get("stock_code") for o in order_list if o.get("stock_code")}
    strikes = {o.get("strike_price") for o in order_list if o.get("strike_price")}
    tenors = {o.get("tenor") for o in order_list if o.get("tenor")}

    stock_count = len(stocks)
    strike_count = max(len(strikes), 1)
    tenor_count = max(len(tenors), 1)
    combo_count = stock_count * strike_count * tenor_count

    limit = OptionParamLimit(
        stock_count=stock_count,
        strike_count=strike_count,
        tenor_count=tenor_count,
        combo_count=combo_count,
        exceeded=(
            stock_count > 5 or strike_count > 5 or tenor_count > 5 or combo_count > 10
        ),
    )

    if limit.exceeded:
        reason_parts = []
        if stock_count > 5:
            reason_parts.append(f"标的数 {stock_count} > 5")
        if strike_count > 5:
            reason_parts.append(f"执行价数 {strike_count} > 5")
        if tenor_count > 5:
            reason_parts.append(f"期限数 {tenor_count} > 5")
        if combo_count > 10:
            reason_parts.append(f"组合数 {combo_count} > 10")
        limit.reason = "; ".join(reason_parts)

        return {
            "error": f"询价参数超出系统限制：{limit.reason}",
            "trace": [{"node": "check_param_limit", "status": "error",
                       "decision": limit.reason}],
        }

    return {
        "trace": [{"node": "check_param_limit", "status": "success",
                   "output_preview": f"combo={combo_count}"}],
    }


# ==============================================================
# 调用后端 API
# ==============================================================
@safe_node
async def call_option_api(state: AgentState) -> dict[str, Any]:
    """调用 /admin-api/option-order/operate。对应 Dify 期权工具的 `期权API`。"""
    if state.get("error"):
        # 前面已有错误，跳过 API 调用
        return {
            "api_code": 400,
            "api_result": state.get("error"),
            "trace": [{"node": "call_option_api", "status": "skip"}],
        }

    wx = state["wechat_input"]
    intent = state.get("intent", "unknown")
    operate = state.get("operate", "")
    order_list = state.get("order_list", [])

    async with OtcBackendClient() as client:
        resp = await client.financial_orders_operate(
            conversationId=wx.get("conversation_id", ""),
            messageId=wx.get("message_id", ""),
            messageContent=wx.get("raw_content", ""),
            rawContent=wx.get("raw_content", ""),
            quoteContent=wx.get("quote_content"),
            quoteAppinfo=wx.get("quote_appinfo"),
            userId=wx.get("user_id", ""),
            roomId=wx.get("room_id", ""),
            guid=wx.get("guid", ""),
            operate=operate,
            type=intent,
            orderList=order_list,
        )

    return {
        "api_code": resp.get("code"),
        "api_result": resp.get("result"),
        "trace": [{
            "node": "call_option_api",
            "output_preview": f"code={resp.get('code')}",
        }],
    }


# ==============================================================
# 构建子图
# ==============================================================
def build_option_graph():
    """期权子图。

    拓扑：
        START → detect_quick_query
                    ├─ yes → fast_query_api → END
                    └─ no  → ticker_identify → extract_option
                                                    ↓
                                            check_param_limit
                                                    ↓
                                              call_option_api
                                                    ↓
                                                   END
    """
    from app.subgraphs.ticker import build_ticker_graph

    g = StateGraph(AgentState)

    g.add_node("detect_quick_query", detect_quick_query)
    g.add_node("fast_query_api", fast_query_api)
    g.add_node("ticker_identify", build_ticker_graph().compile())
    g.add_node("extract_option", extract_option)
    g.add_node("check_param_limit", check_param_limit)
    g.add_node("call_option_api", call_option_api)

    g.add_edge(START, "detect_quick_query")
    g.add_conditional_edges(
        "detect_quick_query",
        route_quick_query,
        {"yes": "fast_query_api", "no": "ticker_identify"},
    )
    g.add_edge("fast_query_api", END)
    g.add_edge("ticker_identify", "extract_option")
    g.add_edge("extract_option", "check_param_limit")
    g.add_edge("check_param_limit", "call_option_api")
    g.add_edge("call_option_api", END)

    return g
