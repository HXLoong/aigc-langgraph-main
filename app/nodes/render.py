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


@safe_node
async def render(state: AgentState) -> dict[str, Any]:
    """生成 reply_text，供 API 层透传企微。"""
    # 1. HITL 消歧
    hitl = state.get("ticker_hitl_candidates")
    if hitl:
        return {"reply_text": _format_hitl_card(hitl)}

    # 2. 0 命中（业务节点正常完成但标的为空）
    tickers = state.get("tickers")
    place_params = state.get("place_params")
    if tickers is not None and len(tickers) == 0 and place_params is not None:
        raw_text = (state.get("raw_text") or "")[:40]
        return {"reply_text": _ZERO_HIT_TMPL.format(raw_text=raw_text)}

    # 3. error → 通用兜底
    if state.get("error") is not None:
        return {"reply_text": _ERROR_REPLY}

    # 4. 正常业务路径 → API 层从业务字段构造输出，render 不干预
    return {}
