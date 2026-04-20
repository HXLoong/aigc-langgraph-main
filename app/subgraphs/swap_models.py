"""互换业务的 Pydantic 模型。

用于：
1. with_structured_output 强制 LLM 输出结构化结果，替代 Dify 里的字符串 JSON 清洗
2. 所有互换相关节点的输入/输出校验
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ============================================================
# 意图分类
# ============================================================
SwapIntentType = Literal[
    "place_order_request",      # 请求下单
    "confirm_order",             # 确认下单
    "cancel_order_request",      # 请求撤单
    "confirm_cancel_order",      # 确认撤单
    "confirm_modify_order",      # 确认改单
    "query_order_status",        # 查询订单状态
    "unknown",                   # 兜底
]


class SwapIntentOutput(BaseModel):
    """互换意图识别的结构化输出。

    对应 Dify `互换-节点-意图识别` LLM 节点。
    """
    type: SwapIntentType = Field(..., description="识别到的意图类型")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="", description="判断理由（调试用）")


# ============================================================
# 下单参数
# ============================================================
PriceType = Literal["market", "limit"]  # 市价 / 限价
Direction = Literal["buy", "sell"]       # 买入 / 卖出


class SwapOrderLeg(BaseModel):
    """互换订单的单条交易腿。"""
    stock_code: str = Field(..., description="标的 Wind 代码（必须来自 goats）")
    stock_name: str | None = Field(None, description="标的名称")
    direction: Direction = Field(..., description="买卖方向")
    quantity: int = Field(..., ge=1, description="数量（股数/手数）")
    price_type: PriceType = Field(default="market")
    limit_price: float | None = Field(None, description="限价单价格")

    # 执行方式
    participation_rate: float | None = Field(
        None, ge=0.0, le=1.0,
        description="跟量比例（0~1）",
    )
    time_window_start: str | None = Field(None, description="时间窗开始，HH:MM")
    time_window_end: str | None = Field(None, description="时间窗结束，HH:MM")

    # 可选字段
    counterparty_id: int | None = Field(None, description="交易对手 ID")
    counterparty_name: str | None = None
    product_full_name: str | None = None
    algorithm: str | None = None


class SwapPlaceOrderOutput(BaseModel):
    """请求下单的结构化输出。

    对应 Dify `互换-节点-下单` LLM 节点。
    """
    type: Literal["place_order_request"] = "place_order_request"
    order_list: list[SwapOrderLeg] = Field(..., min_length=1, max_length=50)
    raw_text_preserved: str | None = Field(
        None, description="原始文本（字符级精确保留，防止标点转换）",
    )


# ============================================================
# 订单 ID 相关（用于 confirm / cancel / modify / query）
# ============================================================
class SwapOrderIdOutput(BaseModel):
    """单一 orderId 提取的结构化输出。

    orderId 格式：H-YYYYMMDD-XXXXXXXXXX
    """
    order_id: str = Field(..., pattern=r"^H-\d{8}-[A-Z0-9]{10}$")


class SwapOrderIdListOutput(BaseModel):
    """多 orderId 提取。"""
    order_ids: list[str] = Field(..., min_length=1)


# ============================================================
# 接口响应
# ============================================================
class SwapApiResponse(BaseModel):
    """后端 /admin-api/swap-order/operate 的统一响应。"""
    code: int
    msg: str | None = None
    data: str | dict | list | None = None
