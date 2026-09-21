"""Generate evidence schemas from canonical models and verify every supplied leaf."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from functools import cache
from types import GenericAlias
from typing import Any, TypeVar, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from app.extraction.fields import FieldCandidate, FieldRecord
from app.wire_model import WireModel

logger = logging.getLogger(__name__)
Canonical = TypeVar("Canonical", bound=BaseModel)


class CandidatePayload(WireModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def report_unknown_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            allowed = set(cls.model_fields) | {f.alias for f in cls.model_fields.values() if f.alias}
            unknown = set(value) - allowed
            if unknown:
                logger.warning("ignored extraction fields: model=%s fields=%s", cls.__name__, sorted(unknown))
        return value


def _candidate_annotation(annotation: Any) -> Any:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return candidate_model(annotation)
    if get_origin(annotation) is list:
        (element,) = get_args(annotation)
        return GenericAlias(list, _candidate_annotation(element))
    return FieldCandidate | None


@cache
def candidate_model(canonical: type[BaseModel]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for name, info in canonical.model_fields.items():
        annotation = _candidate_annotation(info.annotation)
        description = "只抽取归一化前的原文证据；" + (info.description or name)
        default: Any
        if get_origin(annotation) is list:
            default = Field(default_factory=list, alias=info.alias, description=description)
        else:
            default = Field(default=None, alias=info.alias, description=description)
        fields[name] = (annotation, default)
    return create_model(canonical.__name__ + "Candidates", __base__=CandidatePayload, **fields)


def evidence_sources(state: Mapping[str, Any], attachments: Mapping[str, str] | None = None) -> dict[str, str]:
    sources = {"raw": state.get("raw_text") or "", "quote": state.get("quote_content") or ""}
    for message in state.get("history_messages") or []:
        if isinstance(message, dict):
            ident, content = message.get("id"), message.get("content")
        else:
            ident, content = getattr(message, "id", None), getattr(message, "content", None)
        if isinstance(ident, str) and isinstance(content, str):
            sources[f"history:{ident}"] = content
    for reference, text in (attachments or {}).items():
        sources[f"attachment:{reference}"] = text
    return sources


def evidence_user(state: Mapping[str, Any]) -> str:
    """Runtime data only; extraction rules live in the prompt asset."""
    return json.dumps({"sources": evidence_sources(state)}, ensure_ascii=False)


def unpack_candidates(
    canonical: type[Canonical], candidates: BaseModel, sources: Mapping[str, str], *, scope: str,
    normalizers: Mapping[str, Callable[[str, FieldCandidate], Any]] | None = None,
) -> tuple[Canonical, dict[str, FieldRecord]]:
    # Validate the contract even when a caller/test returns the wrong model instance.
    raw = candidate_model(canonical).model_validate(candidates.model_dump(by_alias=True))
    records: dict[str, FieldRecord] = {}
    converters = normalizers or {}

    def visit(value: Any, path: str, alias: str = "") -> Any:
        if isinstance(value, FieldCandidate):
            original = value.verify(sources)
            if original is None:
                return None
            converter = converters.get(path) or converters.get(alias)
            normalized = converter(original, value) if converter is not None else original
            records[path] = FieldRecord(
                value=normalized, source="user", evidence=value.evidence,
                origin=value.origin if value.reference is None else f"{value.origin}:{value.reference}",
                confidence=value.confidence,
            )
            return normalized
        if isinstance(value, BaseModel):
            output = {}
            for name, info in type(value).model_fields.items():
                key = info.alias or name
                output[key] = visit(getattr(value, name), f"{path}.{key}", key)
            return output
        if isinstance(value, list):
            return [visit(item, f"{path}.{i}", alias) for i, item in enumerate(value)]
        return value

    return canonical.model_validate(visit(raw, scope)), records


def verify_candidates(candidates: BaseModel, sources: Mapping[str, str]) -> None:
    """Verify a parsed candidate tree before handing it to a pure normalization node."""
    def visit(value: Any) -> None:
        if isinstance(value, FieldCandidate):
            value.verify(sources)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                visit(getattr(value, name))
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(candidates)
