"""checkpoint 清理脚本纯函数测试(改进 B;DB 交互不在单测范围)。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.cleanup_checkpoints import (
    CHECKPOINT_TABLES,
    STALE_THREADS_SQL,
    chunked,
    cutoff_iso,
    delete_sql,
)


class TestCutoff:
    def test_iso_format_comparable(self):
        now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
        c = cutoff_iso(30, now)
        assert c == "2026-07-29T12:00:00"
        # 与 checkpoint $.ts(ISO8601)字典序可比较
        assert c < "2026-08-01T00:00:00"
        assert c > "2026-07-01T00:00:00"


class TestChunked:
    def test_batches(self):
        assert chunked([str(i) for i in range(450)], size=200) == [
            [str(i) for i in range(200)],
            [str(i) for i in range(200, 400)],
            [str(i) for i in range(400, 450)],
        ]

    def test_empty(self):
        assert chunked([]) == []


class TestSql:
    def test_delete_sql_whitelist(self):
        sql = delete_sql("checkpoints", 3)
        assert sql == "DELETE FROM checkpoints WHERE thread_id IN (%s, %s, %s)"

    def test_delete_sql_rejects_unknown_table(self):
        with pytest.raises(AssertionError):
            delete_sql("users; DROP TABLE x", 1)

    def test_order_writes_blobs_then_checkpoints(self):
        assert CHECKPOINT_TABLES == ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

    def test_stale_sql_uses_ts_json(self):
        assert "$.ts" in STALE_THREADS_SQL and "GROUP BY thread_id" in STALE_THREADS_SQL
