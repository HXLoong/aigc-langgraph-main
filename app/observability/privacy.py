"""Telemetry-only projection; business responses and the local audit remain unchanged."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

_PRIVATE_KEYS = frozenset({
    "rawtext", "rawcontent", "messagecontent", "quotecontent", "content", "evidence",
    "historymessages", "replytext", "apiresult", "password", "secret", "apikey", "token",
    "authorization", "userid", "roomid", "guid", "operatoruserid", "shortname", "longname",
    "placeordershortname", "ctptyid", "counterpartyname", "llminputexcerpt", "traceback",
    "user", "langfuseuserid", "exception",
    "sources", "directname", "accountid", "bankaccount", "bankcard", "customername",
    "requestbody", "responsebody", "requestparams", "ocrtext", "transcription",
})
_CREDENTIAL = re.compile(r"(?i)(bearer\s+)[^\s\"',;]+")
_ASSIGNMENT = re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[=:]\s*)[^\s,;]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_PASSWORD = re.compile(r"(\w+(?:\+\w+)?://[^\s/:]+:)[^@\s]+(@)")


def redact_text(text: str) -> str:
    text = _CREDENTIAL.sub(r"\1[redacted]", text)
    text = _ASSIGNMENT.sub(r"\1[redacted]", text)
    text = _URL_PASSWORD.sub(r"\1[redacted]\2", text)
    return _EMAIL.sub("[email]", _PHONE.sub("[phone]", text))


def mask_sensitive(data: Any, **kwargs: Any) -> Any:
    """Langfuse mask callback, including nested Pydantic state and message objects."""
    if isinstance(data, BaseModel):
        data = data.model_dump(by_alias=True)
    if isinstance(data, Mapping):
        field_record = {"value", "source", "evidence", "origin", "locked"}.issubset(data)
        return {
            key: "[redacted]" if (field_record and key == "value")
            or re.sub(r"[_-]", "", re.split(r"[./]", str(key))[-1]).lower() in _PRIVATE_KEYS
            else mask_sensitive(value)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        if len(data) == 2 and isinstance(data[0], str) and data[0] in {
            "system", "user", "assistant", "human", "ai", "tool", "developer",
        }:
            return [data[0], "[redacted]"]
        return [mask_sensitive(item) for item in data]
    return redact_text(data) if isinstance(data, str) else data


def redact_log(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return dict(mask_sensitive(event_dict))
