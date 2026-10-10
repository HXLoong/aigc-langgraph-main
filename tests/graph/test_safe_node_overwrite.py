"""@safe_node 对 trace=Overwrite(...) 的处理（ADR 0024 D2：ingest 重置一轮边界）。"""
from __future__ import annotations

import pytest
from langgraph.types import Overwrite

from app.graph.safe_node import safe_node
from app.graph.state import TraceEntry


@pytest.mark.asyncio
async def test_safe_node_appends_auto_entry_inside_overwrite() -> None:
    @safe_node
    async def resetter(state):  # type: ignore[no-untyped-def]
        return {"trace": Overwrite([])}

    update = await resetter({})
    assert isinstance(update["trace"], Overwrite)
    assert [e.node for e in update["trace"].value] == ["resetter"]


@pytest.mark.asyncio
async def test_safe_node_keeps_explicit_entry_inside_overwrite() -> None:
    @safe_node
    async def resetter(state):  # type: ignore[no-untyped-def]
        return {"trace": Overwrite([TraceEntry(node="resetter", decision="explicit")])}

    update = await resetter({})
    entries = update["trace"].value
    assert len(entries) == 1 and entries[0].decision == "explicit"
