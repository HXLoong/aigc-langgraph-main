"""每轮请求不能借用 checkpoint 的消息身份或授权参考数据。"""
from unittest.mock import AsyncMock

import pytest

from app.api.turn_state import INPUT_FIELD_ALIASES, inputs_to_state
from app.nodes.persist_intent import make_persist_intent
from app.storage.idempotency import InMemoryIdempotencyStore
from tests.test_inquiry_continuation import inquiry_workflow  # noqa: F401


def test_all_turn_inputs_are_explicitly_overwritten():
    current = inputs_to_state({"raw_content": "本轮"})
    assert set(INPUT_FIELD_ALIASES) <= current.keys()
    assert current["message_id"] is None
    assert current["room_id"] == ""
    assert current["operator_user_id"] is None
    assert current["option_counterparties_raw"] is None
    assert current["swap_counterparties_raw"] is None
    assert current["input_files"] == []
    assert "history_messages" not in current


@pytest.mark.parametrize("missing", ["message_id", "room_id"])
def test_missing_current_identity_cannot_submit_again(request, missing):
    client, calls = request.getfixturevalue("inquiry_workflow")
    client.app.state.idempotency_store = InMemoryIdempotencyStore()
    body = {"conversation_id": "same-session", "user": "test-user", "inputs": {
        "raw_content": "确认下单", "quote_content": "Q-20260922-0000000001",
        "room_id": "test-room", "message_id": 902201,
    }}
    assert client.post("/v1/workflows/run", json=body).status_code == 200
    del body["inputs"][missing]
    if missing != "message_id":
        body["inputs"]["message_id"] = 902202
    client.post("/v1/workflows/run", json=body)
    assert len([c for c in calls if c[0] == "operate"]) == 1
    if missing == "message_id":
        assert len([c for c in calls if c[0] == "set-intent"]) == 1


@pytest.mark.parametrize("message_id", [None, 0, -1])
async def test_set_intent_never_writes_missing_or_invalid_message(message_id):
    client = AsyncMock()
    result = await make_persist_intent(lambda: client)({
        "conversation_id": "c", "message_id": message_id,
    })
    client.set_intent.assert_not_called()
    assert result["trace"][0].decision == "skipped:missing_message_id"


@pytest.mark.parametrize("message_id", [None, 0, -1, "-1", "", True, False])
def test_invalid_current_message_never_claims_idempotency_or_submits(request, message_id):
    client, calls = request.getfixturevalue("inquiry_workflow")
    store = InMemoryIdempotencyStore()
    store.begin = AsyncMock(wraps=store.begin)
    client.app.state.idempotency_store = store
    client.post("/v1/workflows/run", json={"user": "test-user", "inputs": {
        "raw_content": "确认下单", "quote_content": "Q-20260922-0000000001",
        "message_id": message_id, "room_id": "test-room",
    }})
    store.begin.assert_not_awaited()
    assert not [c for c in calls if c[0] == "operate"]
