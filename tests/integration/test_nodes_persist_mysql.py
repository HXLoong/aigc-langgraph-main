"""可选本地 MySQL 验收；默认收集，显式 RUN_LOCAL_MYSQL_TESTS=1 时执行。"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.api.nodes import router
from app.config import get_settings
from app.node_execution.executor import NodeExecutor
from app.node_execution.registry import build_registry
from app.storage.mysql import NODE_TRACE, connection_args


@pytest.mark.skipif(os.getenv("RUN_LOCAL_MYSQL_TESTS") != "1", reason="requires local MySQL")
async def test_persist_endpoint_really_inserts_node_trace() -> None:
    import aiomysql

    args = connection_args(get_settings().mysql_uri)
    host, port, user, password, database = (
        args["host"], args["port"], args["user"], args["password"], args["db"]
    )
    assert host in {"localhost", "127.0.0.1", "::1"}, "local acceptance only"
    trace_id = "node-api-" + uuid.uuid4().hex
    app = FastAPI()
    app.include_router(router)
    app.state.node_executor = NodeExecutor(build_registry())
    conn = await aiomysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        db=database,
        autocommit=True,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/nodes/run",
                json={
                    "product": "main",
                    "node": "persist",
                    "state": {
                        "conversation_id": trace_id,
                        "message_id": 1909202601,
                        "trace_id": trace_id,
                        "trace": [
                            {
                                "node": "local_acceptance",
                                "decision": "persist probe",
                                "elapsed_ms": 7,
                            }
                        ],
                    },
                },
            )
        assert response.status_code == 200, response.text
        async with conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT node_name, step_index, duration_ms FROM {NODE_TRACE} WHERE trace_id=%s",
                (trace_id,),
            )
            assert await cursor.fetchall() == (("local_acceptance", 0, 7),)
    finally:
        async with conn.cursor() as cursor:
            await cursor.execute(f"DELETE FROM {NODE_TRACE} WHERE trace_id=%s", (trace_id,))
        conn.close()
