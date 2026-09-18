"""Explicit raw fragments for the close LLM boundary; no production normalization."""
from typing import Any

from pydantic import BaseModel

from app.extraction.candidates import candidate_model
from app.subgraphs.close.models import ClosePlaceParams, HoldingQueryParams


def _field(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        return value
    return {"value": value, "evidence": value, "confidence": 1.0, "origin": "raw"}


def close_candidates(*rows: dict[str, Any]) -> BaseModel:
    return candidate_model(ClosePlaceParams).model_validate({"closeOrderList": [
        {key: _field(value) for key, value in row.items()} for row in rows]})


def holding_candidates(**values: Any) -> BaseModel:
    return candidate_model(HoldingQueryParams).model_validate({
        key: [_field(item) for item in value] if isinstance(value, list) else _field(value)
        for key, value in values.items()})
