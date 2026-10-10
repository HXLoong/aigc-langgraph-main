"""Opt-in field masking for Langfuse and logs; never mutate business state."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.config import get_settings


def _field_name(key: str) -> str:
    """Match aliases and the final field of flattened audit paths."""
    return re.sub(r"[_-]", "", re.split(r"[./]", key)[-1].strip()).lower()


def _mask_fields(data: Any, fields: set[str]) -> Any:
    if isinstance(data, BaseModel):
        data = data.model_dump(by_alias=True)
    if isinstance(data, Mapping):
        return {
            key: "[redacted]" if _field_name(str(key)) in fields else _mask_fields(value, fields)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        # LangChain role tuples represent the same content field as message dictionaries.
        if "content" in fields and len(data) == 2 and isinstance(data[0], str) and data[0] in {
            "system", "user", "assistant", "human", "ai", "tool", "developer",
        }:
            return [data[0], "[redacted]"]
        return [_mask_fields(item, fields) for item in data]
    return data


def mask_sensitive(data: Any, **kwargs: Any) -> Any:
    """Only mask selected structured fields; do not scan or rewrite free-form text."""
    settings = get_settings()
    if not settings.telemetry_masking_enabled:
        return data
    fields = {
        _field_name(field) for field in settings.telemetry_masking_fields.split(",")
        if field.strip()
    }
    return _mask_fields(data, fields) if fields else data


def redact_log(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return dict(mask_sensitive(event_dict))
