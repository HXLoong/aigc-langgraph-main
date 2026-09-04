from __future__ import annotations

from uuid import UUID

import pytest

from scripts import eval_golden


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"product_type": "option", "intent": "new_inquiry"}


class _RecordingClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def post(self, endpoint: str, *, json: dict, timeout: float) -> _Response:
        self.payloads.append(json)
        return _Response()


@pytest.mark.asyncio
async def test_run_one_case_uses_uuid_conversation_id() -> None:
    client = _RecordingClient()
    case = {
        "id": "case-001",
        "raw_content": "贵州茅台欧式看涨，1M",
        "expected": {"product_type": "option", "intent": "new_inquiry"},
    }

    result = await eval_golden.run_one_case(client, case, "/v1/message")

    assert result["passed"] is True
    conversation_id = client.payloads[0]["conversation_id"]
    assert str(UUID(conversation_id)) == conversation_id
    assert conversation_id != "eval-case-001"
