"""期权平仓业务的 Pydantic 模型。

对应 Dify 主工作流中的期权平仓相关节点：
- 期权平仓-意图识别
- 请求下单和确认全部平仓参数提取
- 期权平仓-持仓查询参数提取
- 确认平仓 / 撤单参数提取 / 确认撤单参数提取 / 平仓订单查询

最新 Dify 版本（2026-05）的关键变化：
- `请求下单和确认全部平仓参数提取` 节点新增 `orderList` 输入（包含
  availableNotional / notional / contractCode），用于支持基于比例 / 余量目标
  的平仓金额计算（平一半 / 平X% / 平剩到Xw 等）。
- 新增 Quick-Execution Semantics → POV25（"尽快成交"/"要快"/"跟量" 等映射到
  closeOrderType="POV", closeOrderPovRatio=25）。
- 新增 Pattern A/B/C 隐式价量解析（无 "限价" 关键字时根据 "平" 分隔符
  或两个数字的量级关系拆分价格与名义本金）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class CloseOrderListItem(BaseModel):
    """`/admin-api/financial-orders/query-close-orders` 返回的订单条目。

    用于喂给 `请求下单和确认全部平仓参数提取` 节点的 `orderList` 输入，
    支持基于比例的平仓金额计算（平一半、平X%、平剩到Xw 等）。
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: str | None = Field(None, alias="orderId",
                                  description="平仓订单 ID（CO-YYYYMMDD-XXXX）")
    contract_code: str | None = Field(None, alias="contractCode",
                                       description="合约编号 OPT-/OPTG-")
    notional: float | None = Field(None, description="原始下单名本（元）")
    available_notional: float | None = Field(
        None, alias="availableNotional",
        description="可平仓名本（元），用于比例/余量目标的平仓金额计算",
    )


class ClosePlaceOrderLeg(BaseModel):
    """平仓下单的一条腿（与 Dify 输出 closeOrderList[] 字段对齐）。

    Dify 字段：
    - orderId / internalTradeId：二选一定位平仓目标
    - closeOrderNotionalDelta：本次平仓名本（元，整数字符串）
    - closeOrderType：限价单 / 市价单 / POV / TWAP（中英文混用）
    - closeOrderPrice：限价（数字）
    - closeOrderPovRatio：POV 跟量比例（百分比，整数）
    - closeOrderAlgoStartTime / closeOrderAlgoEndTime：TWAP 时间窗
    - confirmFullClose：是否全部平仓（true / null，绝不输出 false）
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: str | None = Field(None, alias="orderId")
    internal_trade_id: str | None = Field(None, alias="internalTradeId",
                                            description="合约编号 OPT-/OPTG- 开头")
    close_order_notional_delta: str | None = Field(
        None, alias="closeOrderNotionalDelta",
        description="本次平仓名本（元，整数字符串）",
    )
    close_order_type: str | None = Field(None, alias="closeOrderType",
                                          description="限价单 / 市价单 / POV / TWAP")
    close_order_price: float | None = Field(None, alias="closeOrderPrice")
    close_order_pov_ratio: int | None = Field(None, alias="closeOrderPovRatio")
    close_order_algo_start_time: str | None = Field(None, alias="closeOrderAlgoStartTime")
    close_order_algo_end_time: str | None = Field(None, alias="closeOrderAlgoEndTime")
    confirm_full_close: bool | None = Field(None, alias="confirmFullClose")

    # 兼容老字段（保留以避免破坏既有调用方）
    price_type: Literal["market", "limit"] | None = None
    limit_price: float | None = None
    close_amount: float | None = Field(None, description="兼容字段：平仓金额")
    full_close: bool | None = None


class ClosePlaceOrderOutput(BaseModel):
    """请求平仓下单参数。"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    close_order_list: list[ClosePlaceOrderLeg] = Field(
        default_factory=list, alias="closeOrderList",
    )
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
