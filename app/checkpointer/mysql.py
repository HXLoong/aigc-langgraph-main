"""Namespaced saver for langgraph-checkpoint-mysql 3.0.0; startup never performs DDL."""
from __future__ import annotations

import re

from langgraph.checkpoint.mysql import base
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

from app.storage.mysql import CHECKPOINT_TABLES, COLLATION

_TABLE_PATTERN = re.compile(r"\b(checkpoints|checkpoint_blobs|checkpoint_writes|checkpoint_migrations)\b")
_COMMON = {"thread_id", "checkpoint_ns", "checkpoint_ns_hash"}
_COLUMNS = {
    "langgraph_checkpoints": _COMMON | {"checkpoint_id", "parent_checkpoint_id", "type", "checkpoint", "metadata"},
    "langgraph_checkpoint_blobs": _COMMON | {"channel", "version", "type", "blob"},
    "langgraph_checkpoint_writes": _COMMON | {"checkpoint_id", "task_id", "task_path", "idx", "channel", "type", "blob"},
    "langgraph_checkpoint_migrations": {"v"},
    "langgraph_message_log": {"id", "message_id", "conversation_id", "room_id", "user_id", "raw_content", "reply_text", "response_json", "http_status", "created_at"},
    "langgraph_node_trace": {"id", "message_id", "thread_id", "trace_id", "node_name", "step_index", "status", "duration_ms"},
    "langgraph_shadow_compare": {"id", "message_id", "primary_result", "shadow_result", "diff_detail"},
    "langgraph_user_feedback": {"id", "message_id", "feedback_type", "reporter_id"},
    "langgraph_alembic_version": {"version_num"},
}
_PRIMARY_KEYS = {
    "langgraph_checkpoints": ("thread_id", "checkpoint_ns_hash", "checkpoint_id"),
    "langgraph_checkpoint_blobs": ("thread_id", "checkpoint_ns_hash", "channel", "version"),
    "langgraph_checkpoint_writes": ("thread_id", "checkpoint_ns_hash", "checkpoint_id", "task_id", "idx"),
    "langgraph_checkpoint_migrations": ("v",),
}


def _namespace(sql: str) -> str:
    # Only the dependency's static SQL templates enter here; never request values or parameters.
    return _TABLE_PATTERN.sub(lambda match: "langgraph_" + match[0], sql)


class LangGraphMySQLSaver(AIOMySQLSaver):
    UPSERT_CHECKPOINT_BLOBS_SQL = _namespace(base.UPSERT_CHECKPOINT_BLOBS_SQL)
    UPSERT_CHECKPOINTS_SQL = _namespace(base.UPSERT_CHECKPOINTS_SQL)
    UPSERT_CHECKPOINT_WRITES_SQL = _namespace(base.UPSERT_CHECKPOINT_WRITES_SQL)
    INSERT_CHECKPOINT_WRITES_SQL = _namespace(base.INSERT_CHECKPOINT_WRITES_SQL)

    @staticmethod
    def _select_sql(where: str) -> str:
        sql = _namespace(base.SELECT_SQL).replace(
            "CHARACTER SET utf8mb4 PATH", f"CHARACTER SET utf8mb4 COLLATE {COLLATION} PATH",
        )
        return sql.replace("{WHERE}", where)

    @staticmethod
    def _select_pending_sends_sql(num_ids: int) -> str:
        return _namespace(base.SELECT_PENDING_SENDS_SQL).replace(
            "{CHECKPOINT_ID_PLACEHOLDERS}", ",".join(["%s"] * num_ids),
        )

    async def setup(self) -> None:
        """Verify the SQL-installed schema; never migrate/create tables in the Java database."""
        async with self._cursor() as cur:
            placeholders = ",".join(["%s"] * len(_COLUMNS))
            await cur.execute(
                "SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLLATION_NAME AS collation_name "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                f"AND TABLE_NAME IN ({placeholders})", tuple(_COLUMNS),
            )
            columns: dict[str, set[str]] = {}
            for row in await cur.fetchall():
                columns.setdefault(row["t"], set()).add(row["c"])
                if row["collation_name"] not in (None, COLLATION):
                    raise RuntimeError("Checkpoint collation mismatch; check sql/init.sql")
            if any(not expected <= columns.get(table, set()) for table, expected in _COLUMNS.items()):
                raise RuntimeError("Missing checkpoint schema; initialize selected database with sql/init.sql")
            await cur.execute(
                "SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=DATABASE() AND INDEX_NAME='PRIMARY' "
                f"AND TABLE_NAME IN ({placeholders}) ORDER BY TABLE_NAME, SEQ_IN_INDEX", tuple(_COLUMNS),
            )
            keys: dict[str, list[str]] = {}
            for row in await cur.fetchall():
                keys.setdefault(row["t"], []).append(row["c"])
            if any(tuple(keys.get(table, [])) != expected for table, expected in _PRIMARY_KEYS.items()):
                raise RuntimeError("Checkpoint primary key mismatch; check sql/init.sql")
            await cur.execute("SELECT v FROM langgraph_checkpoint_migrations ORDER BY v")
            if [row["v"] for row in await cur.fetchall()] != list(range(len(base.MIGRATIONS))):
                raise RuntimeError("Checkpoint schema version mismatch; check sql/init.sql")

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._cursor(pipeline=True) as cur:
            for table in CHECKPOINT_TABLES:
                await cur.execute(f"DELETE FROM {table} WHERE thread_id = %s", (str(thread_id),))
