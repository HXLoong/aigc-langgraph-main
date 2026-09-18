"""Isolated local schema proves init repeatability, checkpoint recovery, replay and collation."""
import importlib
import os
import re
import uuid
from pathlib import Path

import aiomysql
import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

from app.config import get_settings

pytestmark = pytest.mark.skipif(os.getenv("RUN_LOCAL_MYSQL_TESTS") != "1", reason="local MySQL opt-in")


async def test_shared_schema_roundtrip_and_startup_validation():
    sql = (Path(__file__).resolve().parents[2] / "sql/init.sql").read_text()
    clean = re.sub(r"(?m)^\s*--.*$", "", sql)
    assert not re.search(r"CREATE\s+DATABASE|\bUSE\b|\bGRANT\b", clean, re.I), "unsafe initializer"
    cls = importlib.import_module("app.checkpointer.mysql").LangGraphMySQLSaver
    args = AIOMySQLSaver.parse_conn_string(get_settings().mysql_uri)
    assert args["host"] in {"localhost", "127.0.0.1"}
    database = "langgraph_test_" + uuid.uuid4().hex[:16]
    admin = await aiomysql.connect(**{**args, "db": None}, autocommit=True)
    pool = None
    try:
        async with admin.cursor() as cur:
            await cur.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
        pool = await aiomysql.create_pool(**{**args, "db": database}, autocommit=True,
                                         charset="utf8mb4", init_command="SET NAMES utf8mb4 COLLATE utf8mb4_general_ci")
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("CREATE TABLE java_existing (id INT PRIMARY KEY, value VARCHAR(20))")
            await cur.execute("INSERT INTO java_existing VALUES (1,'保留')")
            for _ in range(2):
                for statement in clean.split(";"):
                    if statement.strip():
                        await cur.execute(statement)
            await cur.execute("SHOW TABLES")
            names = {row[0] for row in await cur.fetchall()}
            assert len(names) == 10 and all(name == "java_existing" or name.startswith("langgraph_") for name in names)
            await cur.execute("SELECT value FROM java_existing WHERE id=1")
            assert (await cur.fetchone())[0] == "保留"
        saver = cls(pool)
        await saver.setup()
        config = {"configurable": {"thread_id": "测试会话", "checkpoint_ns": "子图|嵌套:1"}}
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"中文通道": {"数量": 1000}, "text": "京东"}
        checkpoint["channel_versions"] = {"中文通道": "1", "text": "1"}
        saved = await saver.aput(config, checkpoint, {"source": "input", "step": 0, "parents": {}}, checkpoint["channel_versions"])
        await saver.aput_writes(saved, [("中文通道", {"待写": True})], "task-1")
        restored = await cls(pool).aget_tuple(saved)
        assert restored.checkpoint["channel_values"] == checkpoint["channel_values"]
        assert restored.pending_writes[0][2] == {"待写": True}
        assert len([item async for item in saver.alist(config)]) == 1
        await saver.adelete_thread("测试会话")
        assert await saver.aget_tuple(config) is None
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM langgraph_checkpoint_migrations WHERE v=0")
        with pytest.raises(RuntimeError, match="version|版本"):
            await saver.setup()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("INSERT INTO langgraph_checkpoint_migrations (v) VALUES (0)")
            await cur.execute("DROP TABLE langgraph_message_log")
        with pytest.raises(RuntimeError, match="sql/init.sql"):
            await saver.setup()
    finally:
        if pool is not None:
            pool.close()
            await pool.wait_closed()
        async with admin.cursor() as cur:
            await cur.execute(f"DROP DATABASE `{database}`")
        admin.close()
