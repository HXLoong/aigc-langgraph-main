"""Shared Java schema: initialization and every saver path own only prefixed tables."""
import importlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "langgraph_checkpoints", "langgraph_checkpoint_blobs", "langgraph_checkpoint_writes",
    "langgraph_checkpoint_migrations", "langgraph_message_log", "langgraph_node_trace",
    "langgraph_shadow_compare", "langgraph_user_feedback", "langgraph_alembic_version",
}


def test_initializer_is_complete_database_independent_and_repeatable():
    sql = (ROOT / "sql/init.sql").read_text()
    statements = re.sub(r"(?m)^\s*--.*$", "", sql)
    assert not re.search(r"\b(?:USE|GRANT|FLUSH|DROP|ALTER)\b|CREATE\s+DATABASE", statements, re.I)
    names = re.findall(r"CREATE TABLE IF NOT EXISTS\s+`?(\w+)`?", statements, re.I)
    assert set(names) == TABLES
    assert statements.count("COLLATE=utf8mb4_general_ci") == len(TABLES)
    assert "0900" not in statements
    assert not (ROOT / "sql/schema.sql").exists()


def test_checkpoint_queries_use_prefix_and_explicit_json_table_collation():
    cls = importlib.import_module("app.checkpointer.mysql").LangGraphMySQLSaver
    queries = [cls._select_sql("WHERE thread_id = %(thread_id)s"), cls._select_pending_sends_sql(2)]
    queries += [getattr(cls, name) for name in ("UPSERT_CHECKPOINT_BLOBS_SQL", "UPSERT_CHECKPOINTS_SQL",
                                               "UPSERT_CHECKPOINT_WRITES_SQL", "INSERT_CHECKPOINT_WRITES_SQL")]
    for query in queries:
        assert not re.search(r"\b(checkpoints|checkpoint_blobs|checkpoint_writes)\b", query)
        assert "langgraph_checkpoint" in query
    assert "COLLATE utf8mb4_general_ci" in queries[0]
    assert "%s,%s" in queries[1]


async def test_saver_thread_delete_only_targets_its_three_prefixed_tables():
    cls = importlib.import_module("app.checkpointer.mysql").LangGraphMySQLSaver
    saver = cls(conn=MagicMock())
    cursor = MagicMock(execute=AsyncMock())
    @asynccontextmanager
    async def cursor_context(**kwargs):
        yield cursor
    saver._cursor = cursor_context
    await saver.adelete_thread("a-user-value-containing-checkpoints")
    sqls = [call.args[0] for call in cursor.execute.await_args_list]
    assert len(sqls) == 3
    assert all("DELETE FROM langgraph_checkpoint" in sql for sql in sqls)
    assert all(call.args[1] == ("a-user-value-containing-checkpoints",)
               for call in cursor.execute.await_args_list)


async def test_startup_rejects_missing_schema_without_creating_tables():
    cls = importlib.import_module("app.checkpointer.mysql").LangGraphMySQLSaver
    saver = cls(conn=MagicMock())
    cursor = MagicMock(execute=AsyncMock(), fetchall=AsyncMock(return_value=[]))
    @asynccontextmanager
    async def cursor_context(**kwargs):
        yield cursor
    saver._cursor = cursor_context
    with pytest.raises(RuntimeError, match="sql/init.sql"):
        await saver.setup()
    assert all(call.args[0].lstrip().upper().startswith("SELECT")
               for call in cursor.execute.await_args_list)


def test_mysql_connection_uses_selected_database_and_general_collation():
    module = importlib.import_module("app.storage.mysql")
    args = module.connection_args("mysql+aiomysql://user:p%40ss@localhost:3308/shared_java")
    assert args["db"] == "shared_java" and args["password"] == "p@ss"
    assert args["charset"] == "utf8mb4"
    assert args["init_command"] == "SET NAMES utf8mb4 COLLATE utf8mb4_general_ci"
    with pytest.raises(ValueError, match="database"):
        module.connection_args("mysql://user:pass@localhost:3308")
