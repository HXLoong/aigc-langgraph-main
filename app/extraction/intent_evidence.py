"""Structured intent attribution checked against the exact sources sent to the model."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.extraction.candidates import evidence_sources
from app.extraction.fields import EvidenceError, FieldRecord


class IntentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="支持意图的连续原文片段，不得改写或补造")
    origin: Literal["raw", "quote", "history"] = Field(description="证据来源：本轮消息、引用消息或历史消息")
    reference: str | None = Field(default=None, description="历史消息的原始 ID；raw/quote 不填写")


class IntentEvidenceOutput(BaseModel):
    confidence: float = Field(ge=0, le=1, description="模型对意图的真实置信度，范围 0 到 1；不得由代码默认填充")
    evidence: list[IntentEvidence] = Field(min_length=1, description="支持意图的原文证据；必须包含本轮用户消息，引用和历史只能补充上下文")


def source_payload(state: Mapping[str, Any]) -> str:
    """Only input data; prompt assets own the extraction instructions."""
    from app.prompts import blocks

    return blocks.source_payload(state)


def intent_records(
    result: IntentEvidenceOutput, state: Mapping[str, Any], *, scope: str, value: str,
) -> dict[str, FieldRecord]:
    sources = evidence_sources(state)
    records: dict[str, FieldRecord] = {}
    has_current = False
    for index, evidence in enumerate(result.evidence):
        if evidence.origin == "history":
            if not evidence.reference:
                raise EvidenceError("意图历史证据缺少消息 ID")
            origin = f"history:{evidence.reference}"
        else:
            if evidence.reference is not None:
                raise EvidenceError("本轮和引用意图证据不能指定其它消息")
            origin = evidence.origin
        if not evidence.text.strip() or evidence.text not in sources.get(origin, ""):
            raise EvidenceError("意图证据不在指定原文来源中")
        has_current = has_current or origin == "raw"
        records[f"{scope}.evidence.{index}"] = FieldRecord(
            value=evidence.text, evidence=evidence.text, source="user", origin=origin,
            confidence=result.confidence, locked=True,
        )
    if not has_current:
        raise EvidenceError("意图判断必须包含本轮用户证据，不能仅依据旧消息")
    records[scope] = FieldRecord(
        value=value, source="inferred", evidence="\n".join(e.text for e in result.evidence),
        origin="raw", confidence=result.confidence, locked=True,
    )
    return records
