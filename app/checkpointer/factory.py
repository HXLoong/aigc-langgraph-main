"""MySQL Checkpointer 工厂。

使用固定版本 langgraph-checkpoint-mysql 3.0.0 与本项目的表名前缀适配层。

关键点：
1. saver 持有 **aiomysql 连接池**（ADR 0024 D4）：社区包 `from_conn_string` 只持有一条连接、
   saver 内部用一把锁串行化全部 IO 且无重连，连接被 wait_timeout 杀掉后全站失忆——生产禁用；
   池的 `pool_recycle` 小于 wait_timeout，探针（`probe_checkpointer`）打的就是这个池
2. 首次运行前执行 sql/init.sql；.setup() 只校验 langgraph_ 表，不执行 DDL
3. MySQL 版本要求：8.0.19 ≤ version < 9.6.0
4. 要求连接使用 autocommit=True
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiomysql
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.checkpointer.mysql import LangGraphMySQLSaver as AIOMySQLSaver
from app.config import get_settings
from app.storage.mysql import connection_args

logger = logging.getLogger(__name__)

#: checkpoint 里允许反序列化的本项目模型（ADR 0024 D4）。langgraph-checkpoint 4.x 的
#: permissive 默认会在未来版本 block 未登记类型；与 tests/test_api_turn_inputs.py 白名单一致。
CHECKPOINT_ALLOWED_MODELS: tuple[tuple[str, str], ...] = (
    ("app.graph.state", "TickerCandidate"),
    ("app.graph.state", "Message"),
    ("app.graph.state", "TraceEntry"),
    ("app.graph.state", "ErrorInfo"),
    ("app.extraction.fields", "FieldRecord"),
)


def build_checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=list(CHECKPOINT_ALLOWED_MODELS))


# 全局单例（由 FastAPI lifespan 管理）
_checkpointer: AIOMySQLSaver | None = None
_pool: Any | None = None  # aiomysql.Pool；probe_checkpointer 与 close 共用


async def init_checkpointer() -> AIOMySQLSaver:
    """在应用启动时调用：建连接池 → 构造 saver → 只读校验初始化结果。"""
    global _checkpointer, _pool

    settings = get_settings()
    logger.info("正在初始化 MySQL Checkpointer（连接池）...")

    conn_kwargs = connection_args(settings.checkpoint_mysql_uri)
    _pool = await aiomysql.create_pool(
        **conn_kwargs,
        autocommit=True,  # 社区包硬要求
        minsize=settings.checkpoint_pool_minsize,
        maxsize=settings.checkpoint_pool_maxsize,
        pool_recycle=settings.checkpoint_pool_recycle_seconds,
    )
    _checkpointer = AIOMySQLSaver(conn=_pool, serde=build_checkpoint_serde())

    try:
        await _checkpointer.setup()
    except BaseException:
        await close_checkpointer()
        raise
    logger.info("MySQL Checkpointer 初始化完成")
    return _checkpointer


async def close_checkpointer() -> None:
    """应用关闭时调用，关闭连接池。"""
    global _checkpointer, _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        _checkpointer = None
        logger.info("MySQL Checkpointer 已关闭")


def get_checkpointer() -> AIOMySQLSaver:
    """供图构建时使用。"""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer 未初始化，确认 FastAPI lifespan 已启动")
    return _checkpointer


def has_checkpointer_pool() -> bool:
    return _pool is not None


async def probe_checkpointer() -> None:
    """/ready 用：从 saver 自己的连接池取一条连接 SELECT 1（ADR 0024 D4）。

    另开新连接探测会在 saver 连接已死时仍返回 ok，故障静默。
    """
    if _pool is None:
        raise RuntimeError("checkpointer_pool_not_initialized")
    async with _pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
        await cur.fetchone()


@asynccontextmanager
async def checkpointer_lifespan() -> AsyncIterator[AIOMySQLSaver]:
    """便于在 FastAPI lifespan 中使用的辅助函数。"""
    cp = await init_checkpointer()
    try:
        yield cp
    finally:
        await close_checkpointer()
