"""互换业务的 Pydantic 模型。

用于：
1. with_structured_output 强制 LLM 输出结构化结果，替代 Dify 里的字符串 JSON 清洗
2. 所有互换相关节点的输入/输出校验

命名规约：
- 内部字段一律 snake_case（符合 Python 风格）
- 通过 Field alias 对齐 Dify 原提示词里的 camelCase 字段名
- populate_by_name=True 允许两种方式构造（业务代码传 snake_case，LLM 传 camelCase）
- BeforeValidator 对枚举值做大小写/命名归一化（Dify "BUY" / "MarketOrder" → "buy" / "market"）
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

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
# 值域归一化：Dify prompt 里使用大写/CamelCase，归一到 snake_case 小写
# ============================================================
def _norm_direction(v: Any) -> Any:
    """BUY/SELL → buy/sell。"""
    return v.lower() if isinstance(v, str) else v


def _norm_price_type(v: Any) -> Any:
    """MarketOrder/LimitOrder → market/limit。"""
    if not isinstance(v, str):
        return v
    mapping = {"marketorder": "market", "limitorder": "limit"}
    return mapping.get(v.lower(), v.lower())


Direction = Annotated[Literal["buy", "sell"], BeforeValidator(_norm_direction)]
PriceType = Annotated[Literal["market", "limit"], BeforeValidator(_norm_price_type)]


# ============================================================
# 下单参数
# ============================================================
class SwapOrderLeg(BaseModel):
    """互换订单的单条交易腿。

    字段设计：
    - 核心字段保留非空约束（stock_code / direction / quantity）
    - 其余一律可选，允许 LLM 输出 null（参数未提取完整时）
    - 通过 alias 对齐 Dify 原提示词中的 placeOrderXxx 命名
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # 核心必填
    stock_code: str = Field(
        ..., alias="placeOrderWindCode",
        description="标的 Wind 代码（必须来自 goats）",
    )
    direction: Direction = Field(
        ..., alias="placeOrderOrderDirection",
        description="买卖方向",
    )
    # 数量字段：股 与 手 互斥（最新 Dify 拆分规则，2026-05）
    # - 用户明确说"股"或仅给纯数字 → quantity
    # - 用户明确说"手" → quantity_hand
    # 两者均允许 None（参数补充场景），上层 (call_swap_api) 会校验至少一个非空
    quantity: int | None = Field(
        None, ge=1, alias="placeOrderQuantity",
        description="数量（股），用户明确说\"股\"或仅给纯数字时填写",
    )
    quantity_hand: int | None = Field(
        None, ge=1, alias="placeOrderQuantityHand",
        description="数量（手），用户明确说\"手\"时填写；非期货标的会经"
                    "互换-手转为股节点换算到 quantity",
    )

    # 价格相关
    price_type: PriceType = Field(default="market", alias="placeOrderPriceType")
    limit_price: float | None = Field(None, alias="placeOrderPrice")

    # 执行算法
    algorithm: str | None = Field(None, alias="placeOrderAlgorithmType")
    participation_rate: float | None = Field(
        None, ge=0.0, le=100.0, alias="placeOrderPovPercent",
        description="POV 跟量比例（百分比 0~100，与 Dify 一致）",
    )
    total_pov_percent: float | None = Field(
        None, ge=0.0, le=100.0, alias="placeOrderTotalPovPercent",
    )
    time_window_start: str | None = Field(None, alias="placeOrderStartTime")
    time_window_end: str | None = Field(None, alias="placeOrderEndTime")
    relative_time_minutes: int | None = Field(None, alias="placeOrderRelativeTimeMinutes")

    # 交易对手
    counterparty_name: str | None = Field(None, alias="placeOrderShortname")
    counterparty_id: int | None = None  # Dify 侧无此字段，仅业务层使用
    product_full_name: str | None = None

    # 数量拆分
    display_qty: int | None = Field(None, alias="placeOrderDisplayQty")
    quantity_total: int | None = Field(None, alias="placeOrderQuantityTotal")

    # 期货专属
    ultra_contract_code: str | None = Field(None, alias="placeOrderUltraContractCode")
    transaction_type: str | None = Field(
        None, alias="placeOrderTransactionType",
        description="A_SHARE / HK_STOCK / FUTURES 等",
    )

    # 订单号（改单/撤单时 LLM 会回填）
    order_id: str | None = Field(None, alias="orderId")

    # 标的名称（Pydantic 保留字段，Dify 原提示词不单独输出）
    stock_name: str | None = None


class SwapPlaceOrderOutput(BaseModel):
    """请求下单的结构化输出。

    对应 Dify `互换-节点-下单` LLM 节点。
    注意：order_list 用 alias="orderList" 对齐 Dify。
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: Literal["place_order_request"] = "place_order_request"

    order_list: list[SwapOrderLeg] = Field(
        default_factory=list, alias="orderList", min_length=1, max_length=50,
    )

    raw_text_preserved: str | None = Field(
        None, description="原始文本（字符级精确保留，防止标点转换）",
    )


# ============================================================
# 订单 ID 相关（用于 confirm / cancel / modify / query）
# ============================================================
SWAP_ORDER_ID_PATTERN = r"^H-\d{8}-[A-Z0-9]{10}$"


class SwapOrderIdItem(BaseModel):
    """单条 orderId 条目（与 Dify confirm/cancel 输出 orderList[].orderId 对齐）。"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: str | None = Field(None, alias="orderId")


class SwapOrderIdOutput(BaseModel):
    """互换 confirm/cancel/modify/query 共用的结构化输出。

    最新 Dify 提示词改为：从 quote_content 中提取**所有** orderId（而非单个），
    输出格式 `{type, orderList: [{orderId}, ...]}`。
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: str | None = None  # confirm_order / cancel_order_request / ...
    order_list: list[SwapOrderIdItem] = Field(
        default_factory=list, alias="orderList", min_length=1, max_length=50,
    )

    @property
    def order_ids(self) -> list[str]:
        """所有非空 orderId 的去重列表（保持出现顺序）。"""
        seen: set[str] = set()
        result: list[str] = []
        for item in self.order_list:
            oid = item.order_id
            if oid and oid not in seen:
                seen.add(oid)
                result.append(oid)
        return result


# ============================================================
# 接口响应
# ============================================================
class SwapApiResponse(BaseModel):
    """后端 /admin-api/swap-order/operate 的统一响应。"""
    code: int
    msg: str | None = None
    data: str | dict | list | None = None
