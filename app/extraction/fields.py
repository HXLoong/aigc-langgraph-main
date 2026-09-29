"""字段来源账本：保留提取值、原文与同次调用锁，不负责业务归一化。"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

FieldSource = Literal["user", "inferred", "goats", "default"]






class EvidenceError(ValueError):
    """A model candidate cannot be traced to the supplied input."""




class FieldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Any = Field(description="待提交的提取值；已核对来源，不代表业务校验通过")
    source: FieldSource = Field(description="代码赋予的来源：用户、推断候选、GOATS 或规则默认值")
    evidence: str = Field(default="", description="原文证据或权威结果引用")
    origin: str = Field(default="raw", description="证据所在的本轮、引用、历史或附件位置")
    confidence: float | None = Field(default=None, ge=0, le=1, description="模型原始置信度；确定性值可以为空")
    locked: bool = Field(default=False, description="当前指令/订单范围内已核对来源，不再允许静默覆盖")
    rejected_updates: int = Field(default=0, ge=0, description="被拒绝的锁定字段修改次数")
    derived_from: list[str] = Field(default_factory=list, description="Code 合并多个来源时引用的原始字段记录路径")


def merge_fields(
    left: dict[str, FieldRecord] | None, right: dict[str, FieldRecord] | None,
) -> dict[str, FieldRecord]:
    """Keys include instruction/order/field identity; resets use Overwrite at turn entry."""
    result = dict(left or {})
    for key, proposed in (right or {}).items():
        previous = result.get(key)
        if previous is not None and previous.locked:
            if previous.value != proposed.value:
                result[key] = previous.model_copy(update={"rejected_updates": previous.rejected_updates + 1})
                logger.warning("locked field update rejected: field=%s", key)
            continue
        result[key] = proposed
    return result
