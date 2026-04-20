"""期权平仓业务的 Pydantic 模型。

对应 Dify 主工作流中的期权平仓相关节点：
- 期权平仓-意图识别
- 请求下单和确认全部平仓参数提取
- 期权平仓-持仓查询参数提取
- 确认平仓 / 撤单参数提取 / 确认撤单参数提取 / 平仓订单查询
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CloseIntentType = Literal[
    "close_order_query",          # 持仓查询
    "close_order_request",        # 请求平仓
    "close_order_confirm",        # 确认平仓
    "close_order_cancel",         # 撤单
    "close_order_confirm_cancel", # 确认撤单
    "close_order_query_status",   # 订单查询
    "unknown",
]


class CloseIntentOutput(BaseModel):
    """期权平仓意图识别输出。"""
    type: CloseIntentType


class CloseHoldingQueryOutput(BaseModel):
    """持仓查询参数。"""
    closeable_only: bool = False
    internal_trade_id_list: list[str] = Field(default_factory=list)
    key_ctpty_id_list: list[int] = Field(default_factory=list)
    ins_family_list: list[str] = Field(default_factory=list)   # EQUITY/FUTURE/INDEX...
    underlying_ins_id_list: list[str] = Field(default_factory=list)
    underlying_ins_name_list: list[str] = Field(default_factory=list)


class ClosePlaceOrderLeg(BaseModel):
    """平仓下单的一条腿。"""
    internal_trade_id: str = Field(..., description="合约编号，OPT-/OPTG- 开头")
    price_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    close_amount: float | None = Field(None, description="平仓金额或数量")
    full_close: bool = False


class ClosePlaceOrderOutput(BaseModel):
    """请求平仓下单参数。"""
    close_order_list: list[ClosePlaceOrderLeg] = Field(default_factory=list)
    error_order_ids: list[str] = Field(default_factory=list,
                                        description="从引用中识别到但参数不完整的 ID")
    full_close_ids: list[str] = Field(default_factory=list)


class CloseOrderNoListOutput(BaseModel):
    """订单号列表（CO- 开头，用于 confirm/cancel/query）。

    订单号格式：CO-YYYYMMDD-XXXXXXXX（8 位十六进制）
    """
    order_no_list: list[str] = Field(
        default_factory=list,
        description="CO-YYYYMMDD-HHHHHHHH 格式的订单号",
    )
