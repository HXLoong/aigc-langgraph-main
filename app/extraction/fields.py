"""Candidate evidence is untrusted; only Code produces canonical field records."""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

FieldSource = Literal["user", "inferred", "goats", "default"]
EvidenceOrigin = Literal["raw", "quote", "history", "attachment"]


class EvidenceError(ValueError):
    """A model candidate cannot be traced to the supplied input."""


class FieldCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(description="归一化前的完整原文值，保留单位和字符；未提及为 null")
    evidence: str = Field(default="", description="支持此值的原文连续片段，不得改写")
    confidence: float = Field(ge=0, le=1, description="语义抽取置信度，不能替代证据校验")
    origin: EvidenceOrigin = Field(default="raw", description="证据来源：本轮原文、引用、历史或附件")
    reference: str | None = Field(default=None, description="历史消息 ID 或附件行列引用；本轮原文和引用为空")

    def verify(self, sources: Mapping[str, str]) -> str | None:
        if self.value is None:
            return None
        key = self.origin if self.origin in {"raw", "quote"} else f"{self.origin}:{self.reference}"
        source = sources.get(key, "")
        if not self.value or not self.evidence or self.value not in self.evidence or self.evidence not in source:
            raise EvidenceError("invalid field evidence")
        if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", self.value) and not re.search(
            r"(?<![0-9.])" + re.escape(self.value) + r"(?![0-9.])", self.evidence,
        ):
            raise EvidenceError("numeric evidence is part of a different value")
        return self.value


class FieldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Any = Field(description="由代码归一化并校验后的值")
    source: FieldSource = Field(description="代码赋予的来源：用户、推断候选、GOATS 或规则默认值")
    evidence: str = Field(default="", description="原文证据或权威结果引用")
    origin: str = Field(default="raw", description="证据所在的本轮、引用、历史或附件位置")
    confidence: float | None = Field(default=None, ge=0, le=1, description="模型原始置信度；确定性值可以为空")
    locked: bool = Field(default=False, description="当前指令/订单范围内已完成校验，不再允许覆盖")
    rejected_updates: int = Field(default=0, ge=0, description="被拒绝的锁定字段修改次数")


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
