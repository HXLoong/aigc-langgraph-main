"""Recovery invariants across real LangGraph merges and checkpoint serialization."""
from unittest.mock import AsyncMock

import pytest

from app.checkpointer.factory import build_checkpoint_serde
from app.graph.state import Message, TraceEntry, merge_by_id
from app.storage.node_trace import trace_entry_to_row as _trace_entry_to_row


@pytest.mark.parametrize("item", [Message(role="user", content="original"), TraceEntry(node="original")])
def test_checkpoint_preserves_reducer_identity(item):
    serde = build_checkpoint_serde()
    recovered = serde.loads_typed(serde.dumps_typed(item))
    assert recovered.id == item.id
    assert len(merge_by_id([item], [recovered])) == 1


async def test_invalid_joint_selection_stops_the_whole_batch(monkeypatch):
    """对手或标的选择无效时，整个动作不得部分提交。"""
    from app.subgraphs.swap.graph import build_swap_graph
    from tests.joint_support import instruction_data
    raw, oid = "对手Z，标的99", "H-20260922-0000000001"
    parsed = instruction_data("swap", "place_order_request", raw, orders=[{"orderId": oid}], quote=oid,
        counterparty_picks=[{"idx": 0, "letter": "Z", "evidence": "对手Z", "confidence": .9}],
        ticker_picks=[{"idx": 0, "seq": 99, "evidence": "标的99", "confidence": .9}])
    backend = AsyncMock()
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    result = await build_swap_graph().ainvoke({"raw_text": raw, "quote_content": oid, "parsed_instruction": parsed,
        "swap_counterparties": [{"sort": "A", "shortName": "甲"}],
        "quote_ticker_candidates": [{"orderId": oid, "candidates": [{"seq": 1, "code": "600519.SH"}]}]})
    assert result["error"].node == "swap_apply_picks"
    backend.assert_not_called()


def test_retry_exhausted_audit_row_is_error():
    row = _trace_entry_to_row(TraceEntry(node="read", decision="error:retry_exhausted"), 0, "m", "t")
    assert row[7] == "error"


def test_audit_persistence_runs_after_history_and_render():
    from app.graph.main import build_main_graph

    edges = set(build_main_graph().builder.edges)
    assert ("record_history", "persist") in edges
    assert ("persist", "__end__") in edges
