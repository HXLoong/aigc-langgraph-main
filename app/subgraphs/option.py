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
    _INTENT_TYPE_NORMALIZE,
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
# 标准路径：意图识别 + 参数提取
#
# 最新 Dify（2026-05）把"期权-参数限制检查 + 期权-意图识别"合并为单一节点
# `期权-意图识别、参数提取`（node_id=1755073106378）。我们对应加载
# app/prompts/option/intent_extract.md。参数限制检查仍由后续 check_param_limit
# 节点用纯 Python 实现（更快、更准）。
# ==============================================================


def _resolve_deterministic_intent(raw: str, quote: str) -> str | None:
    """规则确定性意图判定：能 100% 确定时直接返回，不调 LLM。

    返回 None 表示需要 LLM 判断。
    """
    # "-" 快捷确认
    if raw.strip() == "-":
        return "confirm"
    # 撤单：带订单号 → cancel_order
    import re as _re_opt
    if "撤单" in raw or "取消" in raw:
        if _re_opt.search(r"[CQH]-\d{8}-", raw) or _re_opt.search(r"[CQH]-\d{8}-", quote):
            return "cancel_order"
        if "撤单" in quote or "撤单请求" in quote:
            return "cancel_order"
    # 确认下单
    if "确认下单" in raw:
        return "confirm"
    # quote 是询价回复 + 当前有下单关键词 → place_order
    if ("询价详情" in quote or "如需下单" in quote or "名义本金" in quote):
        if any(kw in raw for kw in ("下单", "市价", "限价", "POV", "TWAP")):
            return "place_order"
    # 纯 "确认" 且有 quote 上下文
    if raw.strip() in ("确认", "确认下单", "好的", "可以", "行", "ok", "OK"):
        return "confirm"
    return None


@safe_node
async def extract_option(state: AgentState) -> dict[str, Any]:
    """期权意图识别 + 参数提取（最新 Dify 合并节点）。"""
    from app.llm.clients import get_qwen_thinking
    from app.prompts import load_prompt

    prompt = load_prompt("option", "intent_extract")

    wx = state["wechat_input"]
    history = state.get("history_messages", [])
    resolved = state.get("resolved_tickers", [])
    bot_names = ", ".join(state.get("bot_name_list", []))

    history_str = "\n".join(
        f"[{m.get('role')}] {m.get('content', '')[:200]}" for m in history[-10:]
    )
    resolved_str = "\n".join(
        f"- {t.wind_code} ({t.ins_sht_desc})" for t in resolved
    ) or "(空)"

    raw_content = wx.get("raw_content", "")
    quote_content = wx.get("quote_content", "") or ""

    # 输入包含看似标的代码但没被解析 → 标的无效（通用规则：代码格式但不在池）
    import re as _re_ticker
    _has_code_like = bool(_re_ticker.search(
        r"\d{5,6}[.\s]|[A-Z]{2,6}\d+|L\d{4,}", raw_content
    ))
    if not resolved and _has_code_like:
        return {
            "intent": "new_inquiry",
            "order_list": [],
            "operate": "inquiry",
            "error": "抱歉！标的代码（或标的名称）不在标的池内，无法自动报价，请联系对口销售或交易员。",
            "trace": [{"node": "extract_option", "decision": "invalid_ticker"}],
        }

    # 多轮上下文预判：quote 或 raw 中有询价特征 → 后续消息是下单/确认/改单
    _combined_ctx = f"{raw_content} {quote_content}"
    _from_inquiry = any(kw in _combined_ctx for kw in (
        "询价详情", "如需下单", "名义本金", "期权费率", "标的代码", "标的名称",
        "已收到您的下单指令", "请引用本消息",
    ))

    # "-" 是多轮对话中的快捷确认信号
    if raw_content.strip() == "-":
        return {
            "intent": "confirm",
            "order_list": [],
            "operate": "确认",
            "trace": [{"node": "extract_option", "decision": "dash_as_confirm"}],
        }

    # 术语规范化提示
    term_hint = ""
    raw_lower = raw_content.lower()
    if any(k in raw_lower for k in ("call", "put")):
        term_hint = "\n术语提示：英文 'call' = 看涨期权，'put' = 看跌期权"
    # 多标的提示
    if len(resolved) >= 2:
        codes = ", ".join(t.wind_code for t in resolved[:8])
        term_hint += (
            f"\n多标的提示: 已识别 {len(resolved)} 个标的 ({codes})，"
            "必须为每个标的创建独立的 orderList 对象"
        )
    if not resolved and history_str:
        term_hint += (
            "\n重要上下文提示：当前消息未识别到标的代码，请从 history_query_str 中提取"
            "标的代码、期限等信息，与当前消息的参数合并。"
        )

    user_message = f"""raw_content: {raw_content}
quote_content: {quote_content or '(无)'}
history_query_str: {history_str or '(无)'}
bot_name_list: {bot_names}
resolved_tickers:
{resolved_str}{term_hint}"""

    # 确定性快速路径：无需参数提取的意图直接返回（不调 LLM）
    _fast = _resolve_deterministic_intent(raw_content, quote_content)
    if _fast in ("confirm", "cancel_order"):
        return {
            "intent": _fast,
            "order_list": [],
            "operate": "确认" if _fast == "confirm" else "cancel_order",
            "trace": [{"node": "extract_option", "decision": f"deterministic_{_fast}"}],
        }

    llm = get_qwen_thinking().with_structured_output(OptionExtractOutput)
    try:
        result: OptionExtractOutput = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_message),
        ])
    except Exception as e:
        return {
            "error": f"期权参数解析失败: {e}",
            "trace": [{"node": "extract_option", "status": "error", "error": str(e)}],
        }

    order_dicts = [leg.model_dump(exclude_none=True) for leg in result.order_list]
    normalized = _INTENT_TYPE_NORMALIZE.get(result.type, result.type)
    # 规则修正：常见多轮关键词强制意图
    _rl = raw_content.lower()
    if "确认下单" in raw_content:
        normalized = "confirm"
    elif "撤单" in raw_content:
        normalized = "cancel_order"
    elif "改" in raw_content and ("单" in raw_content or "行权价" in raw_content or "期限" in raw_content):
        normalized = "modify_order"
    elif ("下单" in raw_content or "市价" in raw_content or "限价" in raw_content) and normalized == "new_inquiry":
        normalized = "place_order"
    # 多轮修正：上轮是询价/下单回复，本轮意图需要上下文修正
    if _from_inquiry:
        if normalized in ("new_inquiry", "unknown", ""):
            if any(kw in raw_content for kw in ("确认", "好的", "可以", "行", "下单")):
                normalized = "confirm"
            elif any(kw in raw_content for kw in ("撤消", "取消", "不要", "算了")):
                normalized = "cancel_order"
            else:
                # 上轮是询价回复，本轮任意非确认内容 → 大概率是下单参数
                normalized = "place_order"
    return {
        "intent": normalized,
        "order_list": order_dicts,
        "operate": result.operate,
        "trace": [{
            "node": "extract_option",
            "decision": normalized,
            "output_preview": preview(order_dicts),
        }],
    }


# ==============================================================
# 参数完整性检查
# ==============================================================
@safe_node
async def check_param_completeness(state: AgentState) -> dict[str, Any]:
    """检查询价参数是否完整（标的、方向、期限、行权价）。

    对应 Dify `期权-参数完整性检查`。
    """
    order_list = state.get("order_list", [])
    intent = state.get("intent", "")
    # new_inquiry 时允许空 order_list（LLM 未能解析时的兜底），
    # 只对 modify_order / place_order 等需要明确参数的操作校验
    if not order_list:
        if intent == "new_inquiry":
            return {"trace": [{"node": "check_param_completeness", "decision": "skip_empty_inquiry"}]}
        return {"trace": [{"node": "check_param_completeness", "decision": "skip"}]}
    if intent not in ("new_inquiry", "modify_order"):
        return {"trace": [{"node": "check_param_completeness", "decision": "skip"}]}

    missing_fields: list[str] = []
    for i, order in enumerate(order_list):
        if not order.get("stock_code"):
            missing_fields.append(f"第{i + 1}条：标的代码")
        if not order.get("option_type"):
            missing_fields.append(f"第{i + 1}条：期权类型（欧式/美式）")
        if not order.get("tenor"):
            missing_fields.append(f"第{i + 1}条：期限")

    if missing_fields:
        msg = "询价参数不完整，请补充以下信息：\n" + "\n".join(missing_fields)
        return {
            "error": msg,
            "reply_text": msg,
            "trace": [{"node": "check_param_completeness", "decision": "incomplete"}],
        }

    return {"trace": [{"node": "check_param_completeness", "decision": "complete"}]}


# ==============================================================
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
def _format_reply(intent: str, order_list: list[dict], raw_result: str) -> str:
    """根据意图类型格式化客服回复。"""
    order_no = ""
    if order_list:
        order_no = (
            order_list[0].get("order_no")
            or order_list[0].get("order_id")
            or order_list[0].get("orderId")
            or ""
        )

    if intent == "cancel_order":
        if order_no:
            return (
                f"已接收撤单指令\n单号：{order_no}\n"
                f"请回复\"确认撤单\"以提交撤单申请。"
            )
        return f"已接收撤单指令\n{raw_result}"

    if intent == "confirm":
        if order_no:
            return (
                f"已确认下单\n单号：{order_no}\n"
                f"您的订单已提交，请等待交易员审核。"
            )
        return f"已确认操作\n{raw_result}"

    if intent == "place_order":
        if order_no:
            return (
                f"{raw_result}\n\n"
                f"已收到下单指令（单号：{order_no}），请回复\"确认下单\"以提交订单。"
            )
        return f"{raw_result}\n\n已收到下单指令，请回复\"确认下单\"以提交订单。"

    return raw_result


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

    raw_result = resp.get("result", "")
    api_result = _format_reply(intent, order_list, raw_result)

    return {
        "api_code": resp.get("code"),
        "api_result": api_result,
        "trace": [{
            "node": "call_option_api",
            "output_preview": f"code={resp.get('code')} intent={intent}",
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
    g.add_node("check_param_completeness", check_param_completeness)
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
    g.add_edge("extract_option", "check_param_completeness")
    g.add_edge("check_param_completeness", "check_param_limit")
    g.add_edge("check_param_limit", "call_option_api")
    g.add_edge("call_option_api", END)

    return g
