"""Opt-in local database test; no business backend or model calls."""
import os
import uuid
from urllib.parse import urlsplit

import pytest

from app.api.idempotency import MySQLIdempotencyStore
from app.config import get_settings


@pytest.mark.skipif(os.getenv("RUN_LOCAL_MYSQL_TESTS") != "1", reason="requires local MySQL")
async def test_failed_http_snapshot_survives_a_new_store_instance():
    uri = get_settings().mysql_uri
    address = urlsplit(uri)
    assert address.hostname in {"127.0.0.1", "localhost", "::1"}
    assert address.path == "/otc_goats_ai_trading_dev"
    store = MySQLIdempotencyStore(uri)
    message_id = f"migration-test-{uuid.uuid4().hex}"
    context = dict(conversation_id=message_id, user_id="migration-test", room_id="migration-test", raw_text="schema probe")
    response = {"code": "internal_server_error", "message": "test failure", "status": 502}
    try:
        assert await store.begin(message_id, **context) is None
        await store.complete(
            message_id, reply_text="", product_type="swap", intent="confirm_order",
            api_code=None, api_result=None, error="test failure", latency_ms=1,
            response=response, http_status=502,
        )
        restored = await MySQLIdempotencyStore(uri).begin(message_id, **context)
        assert restored is not None and restored.status == "done"
        assert restored.http_status == 502 and restored.response == response
    finally:
        conn = await store._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM langgraph_message_log WHERE message_id = %s AND user_id = %s",
                    (message_id, "migration-test"),
                )
        finally:
            conn.close()
