"""MySQL Checkpointer 工厂。

使用社区包 langgraph-checkpoint-mysql 3.0+（由 tjni 维护，刻意保持与官方 Postgres 实现同步）。

关键点：
1. AIOMySQLSaver 是异步上下文管理器，生命周期应与 FastAPI 应用绑定
2. 首次运行必须调用 .setup() 自动建表（checkpoint 相关的 4 张系统表）
3. MySQL 版本要求：8.0.19 ≤ version < 9.6.0
4. 要求连接使用 autocommit=True
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

from app.config import get_settings

logger = logging.getLogger(__name__)

# 全局单例（由 FastAPI lifespan 管理）
_checkpointer: AIOMySQLSaver | None = None
_saver_ctx = None  # 上下文管理器引用，用于关闭


async def init_checkpointer() -> AIOMySQLSaver:
    """在应用启动时调用。"""
    global _checkpointer, _saver_ctx

    settings = get_settings()
    logger.info("正在初始化 MySQL Checkpointer...")

    # AIOMySQLSaver.from_conn_string 返回一个异步上下文管理器
    _saver_ctx = AIOMySQLSaver.from_conn_string(settings.checkpoint_mysql_uri)
    _checkpointer = await _saver_ctx.__aenter__()

    # 首次启动自动建表（幂等）
    await _checkpointer.setup()
    logger.info("MySQL Checkpointer 初始化完成")
    return _checkpointer


async def close_checkpointer() -> None:
    """应用关闭时调用，释放连接池。"""
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
