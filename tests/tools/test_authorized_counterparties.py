"""The local runner must use Java's actual user-scoped counterparty contract."""
import httpx
import pytest

from app.tools.ticker_client import TickerClientHttpx


async def test_authorized_counterparty_query_sends_user_room_and_business():
    def handler(request):
        assert dict(request.url.params) == {
            "roomId": "room", "userId": "user", "type": "TRS", "messageId": "123",
        }
        return httpx.Response(200, json={"code": 0, "data": [{"shortName": "backend-owned"}]})

    client = TickerClientHttpx(base_url="http://java.test", transport=httpx.MockTransport(handler))
    assert await client.list_counterparty("room", user_id="user", business_type="TRS", message_id=123) == [
        {"shortName": "backend-owned"}
    ]


async def test_counterparty_failure_is_not_an_empty_authorized_list():
    client = TickerClientHttpx(base_url="http://java.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"code": 401, "msg": "not authorized"})
    ))
    with pytest.raises(ValueError, match="counterparty"):
        await client.list_counterparty("room")
