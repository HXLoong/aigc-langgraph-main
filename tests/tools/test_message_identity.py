"""Real Java Long IDs must never lose digits at the protocol boundary."""
import json

import httpx
import pytest

from app.subgraphs.swap import backend
from app.tools.bot_context import normalize_message_id
from app.tools.swap_client import SwapClientHttpx


@pytest.mark.parametrize("value", ["1789710755464918000", 1789710755464918000, "9223372036854775807"])
def test_java_long_id_is_preserved(value):
    assert normalize_message_id(value) == int(value)


@pytest.mark.parametrize("value", ["9223372036854775808", 9223372036854775808])
def test_out_of_range_id_is_rejected_instead_of_truncated(value):
    with pytest.raises(ValueError, match="message_id"):
        normalize_message_id(value)


async def test_swap_http_payload_preserves_observed_nineteen_digit_id(monkeypatch):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "待补参"})
    client = SwapClientHttpx(base_url="http://identity.test", token="test-only",
                             transport=httpx.MockTransport(handle), dry_run=False)
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: client)
    await backend.call_swap_backend({"message_id": "1789710755464918000", "conversation_id": "c",
                                    "raw_text": "京东买入1000 限价20", "user_id": "u", "room_id": "r"},
                                   intent="place_order_request", order_list=[])
    assert requests[0]["messageId"] == 1789710755464918000
