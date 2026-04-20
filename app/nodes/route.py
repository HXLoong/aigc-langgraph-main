"""产品路由节点：基于规则判断产品类型，不走 LLM。

对应 Dify 主工作流的 `脚本判断期权、互换、其他查询指令` 节点。
"""
from __future__ import annotations

import re
from typing import Any

from app.nodes.common import safe_node
from app.state import AgentState

# 期权平仓订单号 / 合约编号正则
#   平仓单号：CO-YYYYMMDD-XXXXXXXX
#   合约编号：OPT/OPTG + 4-8 位字母 + 6-10 位数字
OPTION_CLOSE_PATTERN = re.compile(
    r"CO-\d{8}-[0-9A-F]{8}|OPTG?-[A-Z]{4,8}\d{6,10}"
)

# 期权平仓关键词
OPTION_CLOSE_KEYWORDS: frozenset[str] = frozenset({
    "我想平仓", "我要平仓", "帮我平仓", "想平仓", "要平仓",
    "我有哪些持仓", "查询持仓", "查看持仓", "持仓情况",
    "我的持仓", "期权持仓", "查持仓", "期权平仓", "持仓",
})

# 期权关键词
OPTION_KEYWORDS: frozenset[str] = frozenset({
    "期权", "看涨", "看跌", "雪球", "欧式", "美式", "香草",
    "询价", "报价", "行权价", "到期日",
})

# 互换关键词
SWAP_KEYWORDS: frozenset[str] = frozenset({
    "互换", "swap", "SWAP", "Swap", "TRS", "收益互换",
    "跟量", "时间窗", "算法",
})


def _hit(text: str, keywords: frozenset[str]) -> bool:
    return any(k in text for k in keywords)


@safe_node
async def route_product(state: AgentState) -> dict[str, Any]:
    """按优先级判断产品类型。

    优先级：
    1. 单号/合约编号格式命中 → option_close
    2. 有附件（图片/Excel） → swap
    3. 关键词匹配 → option_close / swap / option
    4. 否则 → unknown
    """
    wx = state["wechat_input"]
    raw = wx.get("raw_content") or ""
    quote = wx.get("quote_content") or ""
    combined = f"{raw}\n{quote}"
    attachments = wx.get("attachments") or []

    # 规则 1：单号/合约编号格式
    if OPTION_CLOSE_PATTERN.search(combined):
        return {
            "product_type": "option_close",
            "trace": [{"node": "route_product", "decision": "close_pattern_match"}],
        }

    # 规则 2：附件 → 互换
    if attachments:
        return {
            "product_type": "swap",
            "trace": [{"node": "route_product", "decision": "has_attachment"}],
        }

    # 规则 3：关键词匹配（顺序有讲究，先判更具体的）
    if _hit(raw, OPTION_CLOSE_KEYWORDS):
        return {
            "product_type": "option_close",
            "trace": [{"node": "route_product", "decision": "close_keyword"}],
        }
    if _hit(raw, SWAP_KEYWORDS):
        return {
            "product_type": "swap",
            "trace": [{"node": "route_product", "decision": "swap_keyword"}],
        }
    if _hit(raw, OPTION_KEYWORDS):
        return {
            "product_type": "option",
            "trace": [{"node": "route_product", "decision": "option_keyword"}],
        }

    return {
        "product_type": "unknown",
        "trace": [{"node": "route_product", "decision": "no_match"}],
    }


def route_product_condition(state: AgentState) -> str:
    """供 conditional_edges 使用的纯函数路由。"""
    return state.get("product_type", "unknown")
