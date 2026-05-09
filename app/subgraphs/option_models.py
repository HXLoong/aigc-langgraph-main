"""期权业务的 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# ============================================================
# 期权意图与操作
# ============================================================
OptionIntentType = Literal[
    "new_inquiry",             # 新询价
    "existing_command",        # 存量指令（沿用之前已有订单）
    "place_order",             # 下单
    "place_order_from_quote",  # Dify 原版：引用询价结果下单
    "modify_order",            # 改单
    "cancel_order",            # 撤单
    "confirm",                 # 确认
    "confirm_order",           # Dify 原版：确认下单
    "cancel_order_request",    # Dify 原版：请求撤单
    "request_cancel_order",    # Dify 原版：撤单请求（含"撤单"关键词）
    "confirm_cancel_order",    # Dify 原版：确认撤单
    "query_order_status",      # Dify 原版：查询订单状态
    "unknown",
    "unknown_intent",          # Dify 原版：未知意图
]

# Dify 原版提示词中使用的别名 → 代码规范名
_INTENT_TYPE_NORMALIZE: dict[str, str] = {
    "place_order_from_quote": "place_order",
    "confirm_order": "confirm",
    "cancel_order_request": "cancel_order",
    "request_cancel_order": "cancel_order",
    "confirm_cancel_order": "cancel_order",
    "query_order_status": "unknown",
    "unknown_intent": "unknown",
}

OptionType = Literal[
    "欧式看涨", "欧式看跌",
    "美式看涨", "美式看跌",
    "亚式看涨", "亚式看跌",
    "雪球",
    "参与型看涨", "参与型看跌",
]


class OptionOrderLeg(BaseModel):
    """期权订单的单条腿。

    字段同时接受 snake_case（代码）和 camelCase（Dify 提示词 JSON 示例）。"""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    stock_code: str = Field(
        ..., validation_alias=AliasChoices("stock_code", "stockCode"),
        description="标的 Wind 代码",
    )
    stock_name: str | None = None
    option_type: OptionType = Field(
        default="欧式看涨",
        validation_alias=AliasChoices("option_type", "optionType"),
    )
    strike_price: float | None = Field(
        None,
        validation_alias=AliasChoices("strike_price", "strikePercentage"),
        description="行权价（元/股或比例）",
    )
    strike_price_type: Literal["absolute", "percent"] = "absolute"
    tenor: str | None = Field(None, description="期限，如 '3M' / '1Y' / '90D'")
    notional: float | None = Field(
        None,
        validation_alias=AliasChoices("notional", "notionalAmount"),
        description="名义本金",
    )
    quantity: int | None = Field(None, description="手数/股数")
    direction: Literal["buy", "sell"] = "buy"

    order_no: str | None = Field(
        None,
        validation_alias=AliasChoices("order_no", "orderNo", "orderId"),
        description="期权订单号（Q-YYYYMMDD-XXXXXXXX，用于撤单/改单/确认等操作）",
    )

    counterparty_id: int | None = None
    counterparty_name: str | None = None


class OptionIntentOutput(BaseModel):
    """期权意图识别输出。

    type 给默认 'unknown' 避免 LLM 漏字段时直接抛 ValidationError；
    上游节点应根据 type == 'unknown' 决定走兜底分支。
    """
    type: OptionIntentType = "unknown"
    operate: str = Field(default="", description="具体操作（后端接口需要）")


class OptionExtractOutput(BaseModel):

    """期权参数提取输出。

    同上，type 默认 'unknown'，order_list 默认空列表，保证 LLM 部分遵循
    schema 时也能成功解析，再由业务层判断数据完整性。
    """

    type: OptionIntentType = "unknown"
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
