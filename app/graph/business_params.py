"""状态级业务参数模型（ADR 0001 D6 / #160 裁决落地）。

AgentState 的五个业务参数字段（place_params / cancel_params / confirm /
query_filter / close_params）运行时保持 dict（读取侧、checkpoint、eval 零改动），
但**写入必须经过本模块校验**：字段名拼错（extra=forbid）或类型错在节点内
fail-fast，而不是漂到 render/后端才炸。

`_validated` 只 dump 调用方提供的键——输出与历史 dict 逐字节一致，
不会因模型默认值引入新键（避免 harness differ 误报）。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlaceParams(BaseModel):
    """下单/改单/询价参数信封（swap.place_order / option.extract_*）。"""

    model_config = ConfigDict(extra="forbid")

    expected_action: str = ""
    orderList: list[dict[str, Any]] = Field(default_factory=list)


class CancelParams(BaseModel):
    """撤单参数信封（swap 用 orderList；close 用 cancelOrderNoList）。"""

    model_config = ConfigDict(extra="forbid")

    expected_action: str = ""
    orderList: list[dict[str, Any]] = Field(default_factory=list)
    cancelOrderNoList: list[str] = Field(default_factory=list)


class ConfirmResult(BaseModel):
    """确认结果信封（合并 confirm 节点输出，ADR 0001 D5）。"""

    model_config = ConfigDict(extra="forbid")

    action: str = ""
    orderList: list[dict[str, Any]] = Field(default_factory=list)
    confirmOrderNoList: list[str] = Field(default_factory=list)
    confirmCancelOrderNoList: list[str] = Field(default_factory=list)


class QueryFilter(BaseModel):
    """查询过滤信封（swap/option 用 orderList；close 用 queryOrderNoList）。"""

    model_config = ConfigDict(extra="forbid")

    orderList: list[dict[str, Any]] = Field(default_factory=list)
    queryOrderNoList: list[str] = Field(default_factory=list)


class CloseParams(BaseModel):
    """平仓/持仓查询参数信封。

    字段形状由 close 子图 LLM 输出模型（HoldingQueryParams / ClosePlaceParams）
    约束，此处 extra=allow 仅做类型层兜底。
    """

    model_config = ConfigDict(extra="allow")


def _validated(model_cls: type[BaseModel], kw: dict[str, Any]) -> dict[str, Any]:
    """经模型校验后只回吐调用方提供的键（输出与直接写 dict 等价）。"""
    return model_cls(**kw).model_dump(include=set(kw))


def validated_place_params(**kw: Any) -> dict[str, Any]:
    return _validated(PlaceParams, kw)


def validated_cancel_params(**kw: Any) -> dict[str, Any]:
    return _validated(CancelParams, kw)


def validated_confirm(**kw: Any) -> dict[str, Any]:
    return _validated(ConfirmResult, kw)


def validated_query_filter(**kw: Any) -> dict[str, Any]:
    return _validated(QueryFilter, kw)


def validated_close_params(**kw: Any) -> dict[str, Any]:
    return _validated(CloseParams, kw)


__all__ = [
    "PlaceParams",
    "CancelParams",
    "ConfirmResult",
    "QueryFilter",
    "CloseParams",
    "validated_place_params",
    "validated_cancel_params",
    "validated_confirm",
    "validated_query_filter",
    "validated_close_params",
]
