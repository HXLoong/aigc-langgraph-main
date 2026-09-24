"""订单号与合约编号形态的单一来源（互换 H- / 期权开仓 Q- / 期权平仓 CO- / 合约编号 OPT(G)-）。

主图节点（路由规则、引用候选解析、确认记忆）与三个子图都从这里取正则，
不再各自定义或反向依赖子图模块。形态有意保留历史差异：
- 规范形态（*_ORDER_ID）：用户输入提取 / 确认范围校验使用
- 路由形态（ROUTE_*）：一级路由规则判定产品线时使用，比规范形态更窄，行为与历史一致
- 平仓消息结构形态（CLOSE_ORDER_ID_*_TOKEN）：reference_parser 解析 Java 平仓卡使用
"""
from __future__ import annotations

import re

#: 互换订单号 H-YYYYMMDD-XXXXXXXXXX（8 位日期 + 10 位数字，与后端 SwapOrderIdGenerator 一致）
SWAP_ORDER_ID = r"H-\d{8}-\d{10}"
#: 期权开仓单号 Q-YYYYMMDD-XXXX…（4–16 位字母数字）
OPTION_ORDER_ID = r"Q-\d{8}-[A-Za-z0-9]{4,16}"
#: 期权平仓单号 CO-YYYYMMDD-XXXX…（4–16 位字母数字；用户输入大小写不敏感）
CLOSE_ORDER_ID = r"CO-\d{8}-[A-Za-z0-9]{4,16}"
#: 合约编号（OPT- / OPTG-）
CONTRACT_CODE = r"OPTG?-[A-Za-z0-9]+"

#: 两侧不与字母、数字或连字符相连，避免从更长的串里截出订单号
_LEFT_BOUNDARY = r"(?<![A-Za-z0-9-])"
_RIGHT_BOUNDARY = r"(?![A-Za-z0-9-])"


def bounded(pattern: str) -> str:
    """给订单号形态加左右边界。"""
    return f"{_LEFT_BOUNDARY}{pattern}{_RIGHT_BOUNDARY}"


SWAP_ORDER_ID_RE = re.compile(SWAP_ORDER_ID)
OPTION_ORDER_ID_RE = re.compile(bounded(OPTION_ORDER_ID))
CLOSE_ORDER_ID_RE = re.compile(CLOSE_ORDER_ID, re.I)
CONTRACT_CODE_RE = re.compile(CONTRACT_CODE)
#: 七条最终确认路径共用：三条产品线任一订单号
ANY_ORDER_ID_RE = re.compile(bounded(f"(?:{SWAP_ORDER_ID}|{OPTION_ORDER_ID}|{CLOSE_ORDER_ID})"))

#: product_type → 规范订单号正则（ConversationMemory 从后端回复提取订单号用）
ORDER_ID_RE_BY_PRODUCT: dict[str, re.Pattern[str]] = {
    "swap": SWAP_ORDER_ID_RE,
    "option": OPTION_ORDER_ID_RE,
    "option_close": CLOSE_ORDER_ID_RE,
}

#: 一级路由规则使用的窄形态（app/nodes/route_rules.py）
ROUTE_SWAP_ORDER = SWAP_ORDER_ID
ROUTE_OPTION_OPEN_ORDER = r"Q-\d{8}-\d{10}"
ROUTE_OPTION_CLOSE_ORDER = r"CO-\d{8}-[0-9A-F]{8}|OPTG?-[A-Z]{4,8}\d{6,10}"

#: Java 平仓卡「单号：」行的严格 8 位十六进制形态
CLOSE_ORDER_ID_EXACT8_TOKEN = r"CO-\d{8}-[0-9A-F]{8}"
#: 平仓错误 / 全平 / 裸文本提取使用的 8 位以上十六进制形态
CLOSE_ORDER_ID_STRICT_TOKEN = r"CO-\d{8}-[0-9A-F]{8,}"


__all__ = [
    "ANY_ORDER_ID_RE",
    "CLOSE_ORDER_ID",
    "CLOSE_ORDER_ID_EXACT8_TOKEN",
    "CLOSE_ORDER_ID_RE",
    "CLOSE_ORDER_ID_STRICT_TOKEN",
    "CONTRACT_CODE",
    "CONTRACT_CODE_RE",
    "OPTION_ORDER_ID",
    "OPTION_ORDER_ID_RE",
    "ORDER_ID_RE_BY_PRODUCT",
    "ROUTE_OPTION_CLOSE_ORDER",
    "ROUTE_OPTION_OPEN_ORDER",
    "ROUTE_SWAP_ORDER",
    "SWAP_ORDER_ID",
    "SWAP_ORDER_ID_RE",
    "bounded",
]
