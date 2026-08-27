"""#156 裁决落地：trace_id 贯穿（ADR 0004 关联键补实现）。

- routes/ingest 生成 trace_id 入 state（ingest 兜底，非 API 入口如 eval 也有）
- persist 落 node_trace.trace_id 列 → SQL 与 LangFuse 可按单次调用关联
"""
from __future__ import annotations

from app.nodes.ingest import ingest
from app.nodes.persist import _trace_entry_to_row


class TestIngestTraceId:
    async def test_generates_when_missing(self) -> None:
        result = await ingest({"raw_text": "x", "room_id": "r-1"})
        assert result.get("trace_id"), "ingest 未生成 trace_id"
        assert len(result["trace_id"]) >= 32

    async def test_preserves_existing(self) -> None:
        result = await ingest({"raw_text": "x", "room_id": "r-1", "trace_id": "tid-fixed"})
        assert "trace_id" not in result or result["trace_id"] == "tid-fixed"


class TestPersistTraceId:
    def test_row_contains_trace_id(self) -> None:
        row = _trace_entry_to_row(
            {"node": "n", "decision": "d", "elapsed_ms": 1},
            0,
            "m-1",
            "t-1",
            "tid-abc",
        )
        assert "tid-abc" in row

    def test_insert_sql_has_trace_id_column(self) -> None:
        import inspect

        from app.nodes import persist as persist_mod

        src = inspect.getsource(persist_mod._write_to_mysql)
        assert "trace_id" in src, "INSERT 语句缺 trace_id 列"


def test_state_declares_trace_id() -> None:
    from app.graph.state import AgentState

    assert "trace_id" in AgentState.__annotations__
