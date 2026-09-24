"""共用 Pydantic 模型 + Goats 枚举（对齐 Java SwapEnum / StockEnum）。

字段名保留 Java camelCase 风格便于 1:1 对照。
"""
from __future__ import annotations

from enum import StrEnum

# ============================================================
# Goats 共用枚举（contracts §5）
# ============================================================


class GoatsOrderDirection(StrEnum):
    """交易方向（SwapEnum.java:148）。"""

    BUY = "BUY"
    SELL = "SELL"
    SHORT_OPEN = "SHORT_OPEN"
    SHORT_CLOSE = "SHORT_CLOSE"


class GoatsPriceType(StrEnum):
    """价格类型（SwapEnum.java:182）。"""

    LIMIT_ORDER = "LimitOrder"
    MARKET_ORDER = "MarketOrder"


class GoatsAlgoType(StrEnum):
    """算法类型（SwapEnum.java:213）。"""

    POV = "POV"
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"
    SNIPER = "SNIPER"


class GoatsTransactionType(StrEnum):
    """交易品种类型（SwapEnum.java:59）。"""

    A_SHARE = "A_SHARE"
    HK_STOCK = "HK_STOCK"
    US_STOCK = "US_STOCK"
    SZ_HK_CONNECT = "SZ_HK_CONNECT"
    SH_HK_CONNECT = "SH_HK_CONNECT"
    CHN_FUTURE = "CHN_FUTURE"
    CROSS_FUTURE = "CROSS_FUTURE"

