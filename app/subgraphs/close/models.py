"""close 子图的 Pydantic Output 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.wire_model import WireModel

# ============================================================
# 意图分类（close.intent）
# ============================================================


#: close 子图处理的 7 个意图（6 个 close_order_* + unknown）
CloseIntentType = Literal[
    "close_order_query",  # 平仓查询（持仓查询、按品种查询）
    "close_order_order_query",  # 平仓订单查询（按订单号查状态）
    "close_order_request",  # 平仓请求下单
    "close_order_confirm",  # 确认平仓
    "close_order_cancel_request",  # 平仓请求撤单
    "close_order_cancel_confirm",  # 平仓确认撤单
    "unknown_intent",
]


class CloseIntentOutput(BaseModel):
    """close.intent 节点的 LLM 输出 schema。"""

    model_config = ConfigDict(extra="ignore")

    type: CloseIntentType = Field(description="平仓意图，取 7 个枚举值之一")


# ============================================================
# 持仓查询参数（close.holding_query）
# ============================================================


#: 标的类型枚举（对齐 Java InsFamily）
InsFamily = Literal["EQUITY", "INDEX", "FUND", "FUTURE"]

#: 期权合约类型枚举（对齐 Java ContractType）
ContractType = Literal[
    "EUROPEAN_VANILLA",  # 欧式
    "AUTOCALL",  # 雪球
    "PARTICIPATORY",  # 参与型看涨
    "AIRBAG",  # 安全气囊
]


class HoldingQueryParams(WireModel):
    """close.holding_query 节点的 LLM 输出 schema（与 Dify holding_query.md 字段对齐）。

    驼峰命名匹配 Java DTO；`closeable_only` 是 snake_case 例外（与 prompt 一致）。
    """

    model_config = ConfigDict(extra="ignore")

    closeable_only: bool = Field(description="true = 用户有平仓意图，只查可平持仓；false = 查全部持仓")
    internal_trade_id_list: list[str] = Field(alias="internalTradeIdList", default_factory=list, description="用户提到的合约编号列表（OPT-/OPTG- 开头），未提及 → []")
    key_ctpty_id_list: list[int] = Field(alias="keyCtptyIdList", default_factory=list, description="用户明确指示的交易对手在「交易对手列表」中匹配到的 ctptyId；无指示词 → []；提及但无相似匹配 → 99999999")
    underlying_ins_name_list: list[str] = Field(alias="underlyingInsNameList", default_factory=list, description="用户提到的标的名称列表（个股 / ETF / 指数 / 期货品种中文名或简称，原样输出）")
    underlying_ins_id_list: list[str] = Field(alias="underlyingInsIdList", default_factory=list, description="用户提到的标的代码列表（带交易所后缀原样输出）")
    ins_family_list: list[InsFamily] = Field(alias="insFamilyList", default_factory=list, description="标的类型过滤：EQUITY / INDEX / FUND / FUTURE")
    contract_type_list: list[ContractType] = Field(alias="contractTypeList", default_factory=list, description="期权合约类型过滤：EUROPEAN_VANILLA / AUTOCALL / PARTICIPATORY / AIRBAG")


# ============================================================
# 平仓下单参数（close.place_close）
# ============================================================


#: 平仓订单类型枚举（与 Dify place_close.md 输出值集一致）
ClosePriceType = Literal["市价单", "限价单", "POV", "TWAP"]


class CloseOrderItem(WireModel):
    """closeOrderList 中的单个平仓订单条目（9 字段）。

    与 Dify place_close.md JSON schema 完全对齐。allow null 在所有字段
    （Dify prompt 明确允许 null 表示"用户未提供"）。
    """

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId", description="平仓订单号 CO-YYYYMMDD-XXXXXXXX，或由序号 / 第X笔在 holdingMap 中解析得到")
    internal_trade_id: str | None = Field(default=None, alias="internalTradeId", description="合约编号（OPT-/OPTG-），与 orderId 二选一或同时给出")
    #: 平仓金额（字符串数字，"全部" 时由后端语义而非此字段）
    close_order_notional_delta: str | None = Field(default=None, alias="closeOrderNotionalDelta", description="平仓金额，字符串数字（元）；比例 / 余额表达按规则换算；全部平仓由 confirmFullClose 表达")
    close_order_type: ClosePriceType | None = Field(default=None, alias="closeOrderType", description="平仓方式：市价单 / 限价单 / POV / TWAP；未明确 → null")
    close_order_price: float | int | None = Field(default=None, alias="closeOrderPrice", description="限价价格（数字）")
    close_order_pov_ratio: int | None = Field(default=None, alias="closeOrderPovRatio", description="POV 跟量比例（整数百分比）；「最大跟量」类语义不在此填值")
    #: TWAP 起始时间，格式 "HH:MM"
    close_order_algo_start_time: str | None = Field(default=None, alias="closeOrderAlgoStartTime", description="TWAP 开始时间 HH:MM")
    close_order_algo_end_time: str | None = Field(default=None, alias="closeOrderAlgoEndTime", description="TWAP 结束时间 HH:MM")
    confirm_full_close: bool | None = Field(default=None, alias="confirmFullClose", description="是否全部平仓（全部 / 全平 / 确认全部平仓）")


class ClosePlaceParams(WireModel):
    """close.place_close 节点 LLM 输出。

    顶层结构 `{"closeOrderList": [...]}` 与 Dify prompt 输出契约一致。
    空列表表示"无可绑定订单"或"输入语义为空"。
    """

    model_config = ConfigDict(extra="ignore")

    close_order_list: list[CloseOrderItem] = Field(alias="closeOrderList", default_factory=list, description="平仓订单条目列表；空列表表示无可绑定订单或输入为空")


__all__ = [
    "CloseIntentType",
    "CloseIntentOutput",
    "InsFamily",
    "ContractType",
    "HoldingQueryParams",
    "ClosePriceType",
    "CloseOrderItem",
    "ClosePlaceParams",
]
