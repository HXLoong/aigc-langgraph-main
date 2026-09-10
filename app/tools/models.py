"""共用 Pydantic 模型 + Goats 枚举（对齐 Java SwapEnum / StockEnum）。

字段名保留 Java camelCase 风格便于 1:1 对照。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.wire_model import WireModel

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


class GoatsOrderStatus(StrEnum):
    """订单状态（SwapEnum.java:287，部分常用值）。"""

    DRAFT = "DRAFT"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    PENDING_CANCEL = "PENDING_CANCEL"


class GoatsCurrency(StrEnum):
    """币种（SwapEnum.java:381）。"""

    CNY = "CNY"
    CNH = "CNH"
    HKD = "HKD"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"


# ============================================================
# 机器人上下文（9 个透传字段，contracts §2.1 §3.1）
# ============================================================


class MachineContext(WireModel):
    """企微机器人消息上下文，由 ingest 节点从 Dify inputs 解析后塞进 ReqVO。"""

    model_config = ConfigDict(extra="allow")

    conversation_id: str = Field(alias="conversationId")
    message_id: int = Field(alias="messageId")
    message_content: str = Field(alias="messageContent")
    raw_content: str = Field(alias="rawContent")
    user_id: str = Field(alias="userId")
    room_id: str = Field(alias="roomId")
    quote_content: str | None = Field(default=None, alias="quoteContent")
    quote_appinfo: str | None = Field(default=None, alias="quoteAppinfo")
    guid: str | None = None


# ============================================================
# 通用响应包装（Java CommonResult）
# ============================================================


class CommonResult(BaseModel):
    """Java `CommonResult<T>` 响应包装。"""

    model_config = ConfigDict(extra="allow")

    code: int = 0
    msg: str = ""
    data: Any = None
