"""Model mocks attach evidence from actual input messages, never invented production defaults."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

from pydantic import BaseModel


@dataclass
class IntentReply:
    schema: type[BaseModel]
    fields: dict[str, Any]
    confidence: float

    def __call__(self, messages: list[tuple[str, str]], **kwargs: Any) -> BaseModel:
        user = messages[-1][1]
        marker = user.rfind('{"sources":')
        if marker < 0:
            raise AssertionError("intent mock did not receive source IDs")
        raw = json.loads(user[marker:])["sources"]["raw"]
        if not raw:
            raise AssertionError("empty user input should be handled without a model")
        return self.schema.model_validate({**self.fields, "confidence": self.confidence,
                                          "evidence": [{"text": raw, "origin": "raw"}]})


def intent_reply(schema: type[BaseModel], *, confidence: float = 0.91, **fields: Any) -> IntentReply:
    return IntentReply(schema, fields, confidence)


def mock_ainvoke(value: Any) -> AsyncMock:
    return AsyncMock(side_effect=value) if isinstance(value, IntentReply) else AsyncMock(return_value=value)


def route_reply(label: str, raw: str) -> dict[str, Any]:
    """For tests mocking the private router helper rather than the model boundary."""
    return {"label": label, "confidence": 0.91, "evidence": [{"text": raw, "origin": "raw"}]}
