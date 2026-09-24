"""Generate evidence schemas from canonical models and verify every supplied leaf."""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from functools import cache
from types import GenericAlias
from typing import Any, TypeVar, get_args, get_origin

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, create_model, model_validator

from app.extraction.fields import (
    CandidateDescription,
    CandidateInputName,
    FieldCandidate,
    FieldRecord,
)
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
            for name, info in cls.model_fields.items():
                aliases = {name}
                if info.alias:
                    aliases.add(info.alias)
                if isinstance(info.validation_alias, AliasChoices):
                    aliases.update(choice for choice in info.validation_alias.choices if isinstance(choice, str))
                present = [key for key in aliases if key in value]
                if present and any(value[key] != value[present[0]] for key in present[1:]):
                    raise ValueError(f"conflicting extraction aliases: {name}")
                allowed.update(aliases)
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
    input_names: set[str] = set()
    for name, info in canonical.model_fields.items():
        annotation = _candidate_annotation(info.annotation)
        hint = next((m for m in info.metadata if isinstance(m, CandidateDescription)), None)
        description = hint.text if hint else "只抽取归一化前的原文证据；" + (info.description or name)
        input_hint = next((m for m in info.metadata if isinstance(m, CandidateInputName)), None)
        input_name = input_hint.name if input_hint else info.alias or name
        accepted_names = {name, info.alias or name, input_name}
        if not input_name or accepted_names & input_names:
            raise ValueError("candidate input names must be nonempty and unique")
        input_names.update(accepted_names)
        options: dict[str, Any] = {"alias": info.alias, "description": description}
        if input_hint:
            options.update(validation_alias=AliasChoices(input_name, info.alias or name),
                           serialization_alias=info.alias or name)
        default: Any
        if get_origin(annotation) is list:
            default = Field(default_factory=list, **options)
        else:
            default = Field(default=None, **options)
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
