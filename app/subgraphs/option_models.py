"""期权业务的 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ============================================================
# 期权意图与操作
# ============================================================
OptionIntentType = Literal[
    "new_inquiry",       # 新询价
    "existing_command",  # 存量指令（沿用之前已有订单）
    "place_order",       # 下单
    "modify_order",      # 改单
    "cancel_order",      # 撤单
    "confirm",           # 确认
    "unknown",
]

OptionType = Literal[
    "欧式看涨", "欧式看跌",
    "美式看涨", "美式看跌",
    "亚式看涨", "亚式看跌",
    "雪球",
    "参与型看涨", "参与型看跌",
]


class OptionOrderLeg(BaseModel):
    """期权订单的单条腿。"""
    stock_code: str = Field(..., description="标的 Wind 代码")
    stock_name: str | None = None
    option_type: OptionType = Field(default="欧式看涨")
    strike_price: float | None = Field(None, description="行权价（元/股或比例）")
    strike_price_type: Literal["absolute", "percent"] = "absolute"
    tenor: str | None = Field(None, description="期限，如 '3M' / '1Y' / '90D'")
    notional: float | None = Field(None, description="名义本金")
    quantity: int | None = Field(None, description="手数/股数")
    direction: Literal["buy", "sell"] = "buy"

    counterparty_id: int | None = None
    counterparty_name: str | None = None


class OptionIntentOutput(BaseModel):
    """期权意图识别输出。"""
    type: OptionIntentType
    operate: str = Field(default="", description="具体操作（后端接口需要）")


class OptionExtractOutput(BaseModel):
    """期权参数提取输出。"""
    type: OptionIntentType
    operate: str = ""
    order_list: list[OptionOrderLeg] = Field(default_factory=list)


# ============================================================
# 参数限制校验
# ============================================================
class OptionParamLimit(BaseModel):
    """参数组合数量限制检查。

    对应 Dify `期权-参数限制检查` 节点。
    - 标的数量 ≤ 5
    - 执行价格数量 ≤ 5
    - 期限数量 ≤ 5
    - 组合总数（标的 × 执行价 × 期限） ≤ 10
    """
    stock_count: int = Field(..., ge=0)
    strike_count: int = Field(..., ge=0)
    tenor_count: int = Field(..., ge=0)
    combo_count: int = Field(..., ge=0)
    exceeded: bool
    reason: str = ""
