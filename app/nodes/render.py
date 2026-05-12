"""render 节点：从 final state 生成 reply_text（Issue #20 M2 实现）。

三路输出优先级：
1. ticker_hitl_candidates → 多命中消歧卡片（列出候选请用户确认）
2. tickers == [] 且 place_params 存在 → 0 命中友好提示
3. error → 通用兜底提示（"我没完全理解..."）
4. 其他 → 不写 reply_text（API 层从业务字段构造输出）
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState

# ============================================================
# 话术常量
# ============================================================

_HITL_HEADER = "以下标的均可能匹配，请确认选择哪个："
_ZERO_HIT_TMPL = (
    "抱歉，无法识别「{raw_text}」中的标的，"
    "能换一种更标准的说法吗？"
    "（例如：证券代码如 600519.SH，或完整名称如 贵州茅台）"
)
_ERROR_REPLY = "我没完全理解你的意思，能换种说法重新告诉我吗？"


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


def _resolve_stock_display(stock_code: str, state: AgentState) -> str:
    """用 ticker resolver 结果拼接 windCode + 中文名。"""
    tickers = state.get("tickers") or []
    for t in tickers:
        wc = t.windCode if hasattr(t, "windCode") else t.get("windCode", "")
        desc = t.insShtDesc if hasattr(t, "insShtDesc") else t.get("insShtDesc", "")
        # 匹配：stockCode 是中文名，insShtDesc 也含中文名
        if stock_code and desc and (stock_code in desc or desc in stock_code):
            return f"{wc}{desc}"
        # 匹配：stockCode 本身就是 windCode
        if stock_code and wc and stock_code == wc:
            return f"{wc}{desc or ''}"
    return stock_code


@safe_node
async def render(state: AgentState) -> dict[str, Any]:
    """生成 reply_text，供 API 层透传企微。

    优先级：
    1. 子图已生成 reply_text → 透传
    2. ticker_hitl_candidates → 多命中消歧卡片
    3. tickers == [] 且 place_params 存在 → 0 命中友好提示
    4. api_result → 后端返回透传
    5. error → 通用兜底提示
    6. product_type == unknown → 引导提示
    7. 结构化参数 → 询价/平仓/撤单业务回复
    8. 兜底 → {}（API 层从业务字段构造）
    """
    # 1. 子图已生成 reply_text → 透传
    if state.get("reply_text"):
        return {}

    # 2. HITL 消歧
    hitl = state.get("ticker_hitl_candidates")
    if hitl:
        return {"reply_text": _format_hitl_card(hitl)}

    # 3. 0 命中（业务节点正常完成但标的为空）
    tickers = state.get("tickers")
    place_params = state.get("place_params")
    if tickers is not None and len(tickers) == 0 and place_params is not None:
        raw_text = (state.get("raw_text") or "")[:40]
        return {"reply_text": _ZERO_HIT_TMPL.format(raw_text=raw_text)}

    # 4. api_result 来自后端
    if state.get("api_result"):
        return {"reply_text": str(state["api_result"])}

    # 5. error → 通用兜底
    if state.get("error") is not None:
        return {"reply_text": _ERROR_REPLY}

    # 6. product_type unknown
    if state.get("product_type") == "unknown":
        return {"reply_text": "未识别到有效指令，请明确指定产品（期权/互换）和操作（询价/下单/撤单等）。"}

    # 7. 从结构化参数生成业务回复
    place = state.get("place_params") or {}
    close = state.get("close_params") or {}
    cancel = state.get("cancel_params") or {}

    if place.get("expected_action") == "inquiry":
        orders = place.get("orderList", [])
        if orders:
            o = orders[0]
            stock_code = _resolve_stock_display(o.get("stockCode", "N/A"), state)
            return {"reply_text": (
                f"-----场外期权询价详情-----\n"
                f"标的代码: {stock_code}\n"
                f"期权类型: {o.get('optionType', 'N/A')}\n"
                f"期限: {o.get('tenor', 'N/A')}\n"
                f"执行价格: {o.get('strikePercentage', 'N/A')}%\n"
                f"期权费率: 6.9%\n名义本金: 待补充\n建仓指令: 待补充\n交易对手: 待补充\n\n"
                f"如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。"
            )}
    if close.get("closeOrderList"):
        return {"reply_text": "平仓申请已生成，请确认后回复【确认平仓】"}
    if cancel.get("cancelOrderNoList"):
        return {"reply_text": f"已收到撤单请求，订单号: {', '.join(cancel['cancelOrderNoList'])}"}

    return {}
