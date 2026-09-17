"""MySQL Checkpointer 工厂。

使用社区包 langgraph-checkpoint-mysql 3.0+（由 tjni 维护，刻意保持与官方 Postgres 实现同步）。

关键点：
1. AIOMySQLSaver 是异步上下文管理器，生命周期应与 FastAPI 应用绑定
   （注意：from_conn_string 只持有**一条** aiomysql 连接、saver 内部用锁串行化 IO，
   无重连；ADR 0024 D4 要求生产改为 aiomysql 连接池 —— 待办）
2. 首次运行必须调用 .setup() 自动建表（checkpoints / checkpoint_blobs / checkpoint_writes）
3. MySQL 版本要求：8.0.19 ≤ version < 9.6.0
4. 要求连接使用 autocommit=True
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.config import get_settings

logger = logging.getLogger(__name__)

#: checkpoint 里允许反序列化的本项目模型（ADR 0024 D4）。langgraph-checkpoint 4.x 的
#: permissive 默认会在未来版本 block 未登记类型；与 tests/test_api_turn_inputs.py 白名单一致。
CHECKPOINT_ALLOWED_MODELS: tuple[tuple[str, str], ...] = (
    ("app.graph.state", "TickerCandidate"),
    ("app.graph.state", "Message"),
    ("app.graph.state", "TraceEntry"),
    ("app.graph.state", "ErrorInfo"),
)


def build_checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=list(CHECKPOINT_ALLOWED_MODELS))


# 全局单例（由 FastAPI lifespan 管理）
_checkpointer: AIOMySQLSaver | None = None
_saver_ctx = None  # 上下文管理器引用，用于关闭


async def init_checkpointer() -> AIOMySQLSaver:
    """在应用启动时调用。"""
    global _checkpointer, _saver_ctx

    settings = get_settings()
    logger.info("正在初始化 MySQL Checkpointer...")

    # AIOMySQLSaver.from_conn_string 返回一个异步上下文管理器
    _saver_ctx = AIOMySQLSaver.from_conn_string(
        settings.checkpoint_mysql_uri, serde=build_checkpoint_serde()
    )
    _checkpointer = await _saver_ctx.__aenter__()

    # 首次启动自动建表（幂等）
    await _checkpointer.setup()
    logger.info("MySQL Checkpointer 初始化完成")
    return _checkpointer


async def close_checkpointer() -> None:
    """应用关闭时调用，关闭 saver 持有的连接。"""
    global _checkpointer, _saver_ctx
    if _saver_ctx is not None:
        await _saver_ctx.__aexit__(None, None, None)
        _saver_ctx = None
        _checkpointer = None
        logger.info("MySQL Checkpointer 已关闭")


def get_checkpointer() -> AIOMySQLSaver:
    """供图构建时使用。"""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer 未初始化，确认 FastAPI lifespan 已启动")
    return _checkpointer


@asynccontextmanager
async def checkpointer_lifespan() -> AsyncIterator[AIOMySQLSaver]:
    """便于在 FastAPI lifespan 中使用的辅助函数。"""
    cp = await init_checkpointer()
    try:
        yield cp
    finally:
        await close_checkpointer()
