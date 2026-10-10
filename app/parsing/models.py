"""一次语义解析的产品契约；接口值与原文证据分别表达。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.extraction.intent_evidence import IntentEvidenceOutput
from app.parsing.close_fields import CloseIntentType, CloseOrderItem, HoldingQueryParams
from app.parsing.option_fields import OptionIntentType, OptionOrderItemWithFastExec
from app.parsing.swap_fields import (
    SwapCounterpartyPick,
    SwapIntentType,
    SwapOrderItem,
    SwapTickerPick,
)


class FieldEvidence(BaseModel):
    """定位输出字段的原文来源；提取值可以使用 Java 所需的数字或枚举表达。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="输出字段路径，使用 wire 字段名和零起下标，如 orders.0.stockCode")
    text: str = Field(
        min_length=1, description="支持字段的短连续原文，保留单位、否定或条件；编号优先只复制编号本身，不拼接标签或换行；context 证据取对应原始 JSON 的实际片段，不能把字段名翻译成中文"
    )
    origin: Literal["raw", "quote", "history", "attachment", "context"] = Field(
        description="来源类型；context 仅指提供的只读上下文"
    )
    reference: str | None = Field(
        default=None, description="raw/quote 为 null；其它来源直接复制提供的完整来源键（含前缀），如 history:消息ID、attachment:file:0:sheet:0:row:2:column:A、context:order:0；不能删改键"
    )


class InstructionBase(IntentEvidenceOutput):
    """所有产品共享意图归因与字段来源，来源不等于业务校验成功。"""

    model_config = ConfigDict(extra="forbid")
    fields: list[FieldEvidence] = Field(
        default_factory=list, description="每个非 null 业务字段（包括 false 和 0）必须恰有一条来源记录；path 不可重复；多个来源只选直接支持该值的一处；null 字段不填"
    )
    attachment_rows: list[str] = Field(
        default_factory=list, description="已处理的全部 Excel 数据行来源键，不能遗漏或重复"
    )


class OptionInstruction(InstructionBase):
    """期权询价、开仓、撤单和查询一次解析结果。"""

    product_type: Literal["option"] = Field(default="option", description="产品固定为期权")
    intent: OptionIntentType = Field(
        description="本次唯一期权意图；修改已有订单参数归 place_order_from_quote"
    )
    orders: list[OptionOrderItemWithFastExec] = Field(
        default_factory=list,
        description="Java orderList；新询价展开明确组合；带已有 orderId 的补参、修改或确认只给身份和当前消息/Excel增量，不能复制引用旧参数，其余为 null",
    )


class SwapInstruction(InstructionBase):
    """互换意图、参数及歧义候选选择在同一次请求中完成。"""

    product_type: Literal["swap"] = Field(default="swap", description="产品固定为互换")
    intent: SwapIntentType = Field(description="本次唯一互换意图")
    orders: list[SwapOrderItem] = Field(
        default_factory=list, description="Java orderList；每笔保留独立来源，未提供字段为 null"
    )
    ticker_picks: list[SwapTickerPick] = Field(
        default_factory=list, description="用户明确选择引用候选时填写选择指针，不自行识别证券"
    )
    counterparty_picks: list[SwapCounterpartyPick] = Field(
        default_factory=list, description="用户明确选择对手候选时填写选择指针"
    )


class CloseInstruction(InstructionBase):
    """平仓查询、下单、确认和撤单的联合结果。"""

    product_type: Literal["option_close"] = Field(
        default="option_close", description="产品固定为期权平仓"
    )
    intent: CloseIntentType = Field(description="本次唯一平仓意图")
    orders: list[CloseOrderItem] = Field(
        default_factory=list,
        description="平仓请求参数；只给本次指定的目标及增量；不得复制旧执行参数",
    )
    order_ids: list[str] = Field(
        default_factory=list,
        description="确认、撤销或状态查询的 CO- 订单号，仅来自本次输入或明确引用选择",
    )
    query: HoldingQueryParams | None = Field(
        default=None, description="持仓查询条件；不填写未提到的业务默认值"
    )


class UnknownInstruction(InstructionBase):
    """无法确定业务意图时保留归因，禁止猜测并提交。"""

    product_type: Literal["unknown"] = Field(default="unknown", description="无法确定产品")
    intent: Literal["unknown_intent"] = Field(
        default="unknown_intent", description="无法确定可执行意图"
    )


Instruction = OptionInstruction | SwapInstruction | CloseInstruction | UnknownInstruction


class CrossProductInstruction(BaseModel):
    """产品不明确时返回完整的一个产品结果，后续不再解析。"""

    model_config = ConfigDict(extra="forbid")
    instruction: Annotated[Instruction, Field(discriminator="product_type")] = Field(
        description="选定一个产品和单一意图，并同时提取对应参数及证据"
    )
