"""请求级幂等（ADR 0024 D4，评估 R2）。

Java 超时重试 / 企微重投 / 运维重放同一条消息时，不得重跑整图——确认节点直调后端写接口，
重跑即重复下单 / 重复平仓；此前幂等责任 100% 外包给后端 dedup 且无本地兜底。

以企微 `message_id`（`message_log.uk_message_id`）去重：
- 首次 → 占位（in_progress），跑图，完成后回填回复
- 已完成 → 回放上次 `reply_text`，不重跑图
- 处理中 → 固定文案"正在处理"，不重跑图
- 请求没有 message_id → 不做幂等（评估 / harness 直调路径）

Store 由 lifespan 注入 `app.state.idempotency_store`；存储失败只 warning（幂等是加固，不阻断业务）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import aiomysql
import pymysql

from app.nodes.persist import _parse_mysql_uri

logger = logging.getLogger(__name__)

PROCESSING_NOTICE = "该消息正在处理中，请勿重复提交。"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    message_id: str
    status: Literal["in_progress", "done"]
    reply_text: str | None = None
    api_code: int | None = None


class IdempotencyStore(Protocol):
    async def begin(
        self, message_id: str, *, conversation_id: str, user_id: str, room_id: str, raw_text: str
    ) -> IdempotencyRecord | None:
        """占位；返回 None 表示首次，否则返回已有记录（回放 / 处理中）。"""

    async def complete(
        self,
        message_id: str,
        *,
        reply_text: str | None,
        product_type: str | None,
        intent: str | None,
        api_code: int | None,
        api_result: Any,
        error: str | None,
        latency_ms: int,
    ) -> None: ...


class InMemoryIdempotencyStore:
    """测试 / 单进程开发用。"""

    def __init__(self) -> None:
        self._rows: dict[str, IdempotencyRecord] = {}

    async def begin(self, message_id, *, conversation_id, user_id, room_id, raw_text):  # type: ignore[no-untyped-def]
        existing = self._rows.get(message_id)
        if existing is not None:
            return existing
        self._rows[message_id] = IdempotencyRecord(message_id=message_id, status="in_progress")
        return None

    async def complete(self, message_id, *, reply_text, product_type, intent, api_code, api_result, error, latency_ms):  # type: ignore[no-untyped-def]
        self._rows[message_id] = IdempotencyRecord(
            message_id=message_id, status="done", reply_text=reply_text, api_code=api_code
        )


class MySQLIdempotencyStore:
    """业务库 message_log 表（sql/schema.sql）；每次调用短连接，与 persist.py 同风格。"""

    def __init__(self, business_mysql_uri: str, *, timeout_seconds: float = 5.0) -> None:
        self._conn_args = _parse_mysql_uri(business_mysql_uri)
        self._timeout = timeout_seconds

    async def _connect(self):  # type: ignore[no-untyped-def]
        host, port, user, password, db = self._conn_args
        return await asyncio.wait_for(
            aiomysql.connect(host=host, port=port, user=user, password=password, db=db,
                             charset="utf8mb4", autocommit=True),
            timeout=self._timeout,
        )

    async def begin(self, message_id, *, conversation_id, user_id, room_id, raw_text):  # type: ignore[no-untyped-def]
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        "INSERT INTO message_log (message_id, conversation_id, room_id, user_id, "
                        "raw_content, processed_by) VALUES (%s, %s, %s, %s, %s, %s)",
                        (message_id, conversation_id, room_id, user_id, raw_text, "langgraph"),
                    )
                    return None
                except pymysql.err.IntegrityError:
                    await cur.execute(
                        "SELECT reply_text, api_code FROM message_log WHERE message_id = %s",
                        (message_id,),
                    )
                    row = await cur.fetchone()
                    if row is None:
                        return None
                    reply_text, api_code = row[0], row[1]
                    status: Literal["in_progress", "done"] = "done" if reply_text is not None else "in_progress"
                    return IdempotencyRecord(message_id=message_id, status=status,
                                             reply_text=reply_text, api_code=api_code)
        finally:
            conn.close()

    async def complete(self, message_id, *, reply_text, product_type, intent, api_code, api_result, error, latency_ms):  # type: ignore[no-untyped-def]
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE message_log SET reply_text = %s, product_type = %s, intent = %s, "
                    "api_code = %s, api_result = %s, error = %s, latency_ms = %s "
                    "WHERE message_id = %s",
                    (reply_text if reply_text is not None else "", product_type, intent, api_code,
                     None if api_result is None else str(api_result)[:4096], error, latency_ms,
                     message_id),
                )
        finally:
            conn.close()


__all__ = [
    "PROCESSING_NOTICE",
    "IdempotencyRecord",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "MySQLIdempotencyStore",
]
