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
#   OPT-/OPTG- 前缀宽松匹配：兼容测试占位符如 OPT-NOTEXIST（无尾随数字）
OPTION_CLOSE_PATTERN = re.compile(
    r"CO-\d{8}-[0-9A-F]{8}|OPTG?-[A-Z]{4,8}\d{6,10}|OPTG?-[A-Z]{4,}",
    re.IGNORECASE,
)

# 期权订单号正则（Q-YYYYMMDD-XXXXXXXX，询价/下单/撤单等）
OPTION_ORDER_PATTERN = re.compile(r"Q-\d{8}-\d{8,12}")

# 互换订单号正则：H-YYYYMMDD-XXXXXXXXXX（宽松匹配 4~16 位，兼容用户手输短形式）
SWAP_ORDER_ID_PATTERN = re.compile(r"H-\d{8}-[A-Z0-9]{4,16}")

# "撤单"/"取消" 既可出现在平仓语境也可出现在期权下单后语境
# 单独出现（无平仓上下文、无 CO-* 编号）时应路由到 option 而非 option_close
_GENERIC_CANCEL_KEYWORDS: frozenset[str] = frozenset({"撤单", "取消"})
_CLOSE_SPECIFIC_KEYWORDS: frozenset[str] = frozenset({
    "我想平仓", "我要平仓", "帮我平仓", "想平仓", "要平仓",
    "我有哪些持仓", "查询持仓", "查看持仓", "持仓情况",
    "我的持仓", "期权持仓", "查持仓", "期权平仓", "持仓",
    "平仓", "平剩", "平掉", "平留", "市价平", "全平", "部分平",
    "序号", "合约编号",
})

# 期权关键词
OPTION_KEYWORDS: frozenset[str] = frozenset({
    "期权", "看涨", "看跌", "雪球", "欧式", "美式", "香草",
    "询价", "报价", "行权价", "到期日",
    "call", "put",
})

# 标的+期限兜底模式：无产品关键词但具备期权询价格式特征
# 例：600519.SH,1M / 000001.SZ 3M / 600519.SH,3Y
_STOCK_TENOR_PATTERN = re.compile(r"\d{6}\.[A-Z]{2}.*?\d+[MYDmywd]")

# 互换关键词
SWAP_KEYWORDS: frozenset[str] = frozenset({
    "互换", "swap", "SWAP", "Swap", "TRS", "收益互换",
    "跟量", "时间窗", "算法",
})

# "跟量"也能出现在平仓语境（如「不用跟量，正常挂单」），
# 需结合平仓关键词做互斥判断，避免误路由到 swap
OPTION_CLOSE_CONTEXT: frozenset[str] = frozenset({
    "平", "序号", "合约编号", "全平", "持仓", "订单",
})


def _hit(text: str, keywords: frozenset[str]) -> bool:
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


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

    # 规则 0：未 @机器人且无"快速询价"触发词 → 不响应
    if not state.get("at_bot", False) and "快速询价" not in combined:
        return {
            "product_type": "unknown",
            "reply_text": "",
            "trace": [{"node": "route_product", "decision": "not_mentioned"}],
        }

    # 规则 1：单号/合约编号格式
    if OPTION_CLOSE_PATTERN.search(combined):
        return {
            "product_type": "option_close",
            "trace": [{"node": "route_product", "decision": "close_pattern_match"}],
        }

    # 规则 1.3：期权订单号格式（Q-YYYYMMDD-...）→ 期权操作
    if OPTION_ORDER_PATTERN.search(combined):
        return {
            "product_type": "option",
            "trace": [{"node": "route_product", "decision": "option_order_pattern"}],
        }

    # 规则 1.5：互换订单号格式（H-YYYYMMDD-...）
    if SWAP_ORDER_ID_PATTERN.search(combined):
        return {
            "product_type": "swap",
            "trace": [{"node": "route_product", "decision": "swap_id_pattern_match"}],
        }

    # 规则 2：附件 → 互换
    if attachments:
        return {
            "product_type": "swap",
            "trace": [{"node": "route_product", "decision": "has_attachment"}],
        }

    # 规则 3：关键词匹配。先看 raw_content（原行为），未命中再 fallback 到
    # combined（含 quote_content）—— 处理"用户引用之前消息只回复'确认'"的场景。
    for source_name, source_text in (("raw", raw), ("quote", combined)):
        # 平仓专属关键词 → option_close
        if _hit(source_text, _CLOSE_SPECIFIC_KEYWORDS):
            return {
                "product_type": "option_close",
                "trace": [{"node": "route_product", "decision": f"close_keyword_{source_name}"}],
            }
        # "撤单"/"取消" → 检查 combined（含 quote）是否有平仓上下文
        if _hit(source_text, _GENERIC_CANCEL_KEYWORDS):
            if (OPTION_CLOSE_PATTERN.search(source_text)
                    or OPTION_CLOSE_PATTERN.search(combined)
                    or _hit(source_text, OPTION_CLOSE_CONTEXT)
                    or _hit(combined, OPTION_CLOSE_CONTEXT)):
                return {
                    "product_type": "option_close",
                    "trace": [{"node": "route_product",
                              "decision": f"cancel_with_close_context_{source_name}"}],
                }
            return {
                "product_type": "option",
                "trace": [{"node": "route_product",
                          "decision": f"cancel_to_option_{source_name}"}],
            }
        if _hit(source_text, SWAP_KEYWORDS):
            # 「跟量」可出现在平仓语境（如「不用跟量，正常挂单」），
            # 有平仓上下文时路由到 option_close
            if _hit(source_text, OPTION_CLOSE_CONTEXT):
                return {
                    "product_type": "option_close",
                    "trace": [{"node": "route_product",
                              "decision": f"close_context_{source_name}"}],
                }
            return {
                "product_type": "swap",
                "trace": [{"node": "route_product",
                          "decision": f"swap_keyword_{source_name}"}],
            }
        if _hit(source_text, OPTION_KEYWORDS):
            return {
                "product_type": "option",
                "trace": [{"node": "route_product", "decision": f"option_keyword_{source_name}"}],
            }

    # 规则 4：标的+期限兜底 — 无产品关键词但具备期权询价格式特征
    # 例：600519.SH,1M / 000001.SZ 3M
    if _STOCK_TENOR_PATTERN.search(combined):
        return {
            "product_type": "option",
            "trace": [{"node": "route_product", "decision": "stock_tenor_fallback"}],
        }

    # 无关键词匹配时，回退到历史状态中已有的 product_type（多轮对话延续）
    previous = state.get("product_type")
    if previous and previous != "unknown":
        return {
            "product_type": previous,
            "trace": [{"node": "route_product", "decision": f"fallback_to_{previous}"}],
        }

    return {
        "product_type": "unknown",
        "trace": [{"node": "route_product", "decision": "no_match"}],
    }


def route_product_condition(state: AgentState) -> str:
    """供 conditional_edges 使用的纯函数路由。"""
    return state.get("product_type", "unknown")
