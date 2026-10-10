"""Structured intent attribution checked against the exact sources sent to the model."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.extraction.fields import EvidenceError, FieldRecord
from app.extraction.sources import evidence_sources


class IntentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="支持意图的连续原文片段，不得改写或补造")
    origin: Literal["raw", "quote", "history", "attachment"] = Field(description="证据来源：本轮消息、引用、历史或本次 Excel 单元格")
    reference: str | None = Field(default=None, description="history/attachment 直接复制完整来源键，如 history:消息ID 或 attachment:file:0:sheet:0:row:2:column:A；raw/quote 不填写")


class IntentEvidenceOutput(BaseModel):
    confidence: float = Field(ge=0, le=1, description="模型对意图的真实置信度，范围 0 到 1；不得由代码默认填充")
    evidence: list[IntentEvidence] = Field(min_length=1, description="支持意图的原文证据；包含本轮用户消息或附件，引用和历史只能补充上下文")


def intent_records(
    result: IntentEvidenceOutput, state: Mapping[str, Any], *, scope: str, value: str,
) -> dict[str, FieldRecord]:
    """核对每条意图证据属于指定来源，并要求至少一条本轮依据。"""
    sources = evidence_sources(state, state.get("attachment_sources") or {})
    records: dict[str, FieldRecord] = {}
    has_current = False
    for index, evidence in enumerate(result.evidence):
        if evidence.origin in {"history", "attachment"}:
            if not evidence.reference or not evidence.reference.startswith(f"{evidence.origin}:"):
                raise EvidenceError("意图历史证据缺少消息 ID")
            origin = evidence.reference
        else:
            if evidence.reference is not None:
                raise EvidenceError("本轮和引用意图证据不能指定其它消息")
            origin = evidence.origin
        if not evidence.text.strip() or evidence.text not in sources.get(origin, ""):
            raise EvidenceError("意图证据不在指定原文来源中")
        has_current = has_current or origin == "raw" or evidence.origin == "attachment"
        records[f"{scope}.evidence.{index}"] = FieldRecord(
            value=evidence.text, evidence=evidence.text, source="user", origin=origin,
            confidence=result.confidence, locked=True,
        )
    if not has_current:
        raise EvidenceError("意图判断必须包含本轮用户证据，不能仅依据旧消息")
    records[scope] = FieldRecord(
        value=value, source="inferred", evidence="\n".join(e.text for e in result.evidence),
        origin=next(record.origin for record in records.values()
                    if record.origin == "raw" or record.origin.startswith("attachment:")),
        confidence=result.confidence, locked=True, derived_from=list(records),
    )
    return records
