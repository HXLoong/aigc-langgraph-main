"""@safe_node 单一计时（ADR 0024 D5）：节点自己写的 TraceEntry 也要带 elapsed_ms，
否则 node_trace.duration_ms 恒 NULL（此前只有自动补的条目有耗时）。"""
from __future__ import annotations

import pytest

from app.graph.safe_node import safe_node
from app.graph.state import TraceEntry


@pytest.mark.asyncio
async def test_explicit_entry_of_own_node_gets_elapsed_stamped() -> None:
    @safe_node
    async def worker(state):  # type: ignore[no-untyped-def]
        return {"trace": [TraceEntry(node="worker", decision="done")]}

    update = await worker({})
    (entry,) = update["trace"]
    assert entry.decision == "done" and entry.elapsed_ms is not None and entry.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_existing_elapsed_and_other_nodes_untouched() -> None:
    @safe_node
    async def worker(state):  # type: ignore[no-untyped-def]
        return {"trace": [
            TraceEntry(node="worker", decision="a", elapsed_ms=999),
            TraceEntry(node="summary_of_other", decision="b"),
            {"node": "worker", "decision": "dict-entry"},
        ]}

    update = await worker({})
    first, other, as_dict = update["trace"]
    assert first.elapsed_ms == 999
    assert other.elapsed_ms is None
    assert as_dict["elapsed_ms"] is not None
