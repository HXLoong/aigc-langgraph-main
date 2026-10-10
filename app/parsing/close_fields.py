"""期权平仓接口字段，未提供值不补业务默认。"""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from app.parsing.scalars import CandidateScalar
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
    """本次明确的持仓过滤条件，驼峰字段名与 Java 契约一致。"""

    model_config = ConfigDict(extra="forbid")

    closeable_only: bool | None = Field(default=None, description="本次明确要求只查可平持仓为 true；明确不限可平条件为 false；未限定为 null，不填默认值；非 null 时必须提供 query.closeable_only 的字段证据")
    internal_trade_id_list: list[str] = Field(alias="internalTradeIdList", default_factory=list, description="用户提到的合约编号列表（OPT-/OPTG- 开头），未提及 → []")
    key_ctpty_id_list: list[int] = Field(alias="keyCtptyIdList", default_factory=list, description="用户明确指定且在所提供授权对手列表中唯一对应的 ctptyId；禁止猜测 ID 或填哨兵值")
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
    """本次平仓目标及显式参数；未提供值为空，已有订单由 Java 合并。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(default=None, alias="orderId", description="平仓订单号 CO-YYYYMMDD-XXXXXXXX，或由序号 / 第X笔在 holdingMap 中解析得到")
    internal_trade_id: str | None = Field(default=None, alias="internalTradeId", description="仅填写 raw、quote 或 context.sources 中实际存在的 OPT-/OPTG- 合约号；当前选中条目同时显示单号和合约号时两者都提供；当前仅有 CO- 号且只读上下文没有合约号时必须为 null，history 中的合约号绝不能补入")
    #: 平仓金额（字符串数字，"全部" 时由后端语义而非此字段）
    close_order_notional_delta: CandidateScalar | None = Field(default=None, alias="closeOrderNotionalDelta", description="平仓金额，字符串数字（元）；比例 / 余额表达按规则换算；全部平仓由 confirmFullClose 表达")
    close_order_type: CandidateScalar | None = Field(default=None, alias="closeOrderType", description="平仓方式：市价单 / 限价单 / POV / TWAP；未明确 → null")
    close_order_price: CandidateScalar | None = Field(default=None, alias="closeOrderPrice", description="限价价格（数字）")
    close_order_pov_ratio: CandidateScalar | None = Field(default=None, alias="closeOrderPovRatio", description="POV 跟量比例（百分比数字，保留小数）；默认值、截断和范围校验由 Java 负责")
    has_fast_execution_intent: CandidateScalar | None = Field(default=None, alias="hasFastExecutionIntent", description="是否明确要求最大跟量或快速执行；只传意图，不由此补执行方式或比例")
    #: TWAP 起始时间，格式 "HH:MM"
    close_order_algo_start_time: CandidateScalar | None = Field(default=None, alias="closeOrderAlgoStartTime", description="TWAP 开始时间 HH:MM")
    close_order_algo_end_time: CandidateScalar | None = Field(default=None, alias="closeOrderAlgoEndTime", description="TWAP 结束时间 HH:MM")
    confirm_full_close: CandidateScalar | None = Field(default=None, alias="confirmFullClose", description="是否全部平仓（全部 / 全平 / 确认全部平仓）")


class ClosePlaceParams(WireModel):
    """平仓准备结果的订单列表，不在代码中换算金额或执行方式。"""

    model_config = ConfigDict(extra="forbid")

    close_order_list: list[CloseOrderItem] = Field(alias="closeOrderList", default_factory=list, description="平仓订单条目列表；空列表表示无可绑定订单或输入为空")


__all__ = [
    "CloseIntentType",
    "InsFamily",
    "ContractType",
    "HoldingQueryParams",
    "ClosePriceType",
    "CloseOrderItem",
    "ClosePlaceParams",
]
