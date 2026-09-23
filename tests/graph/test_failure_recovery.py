"""Recovery invariants across real LangGraph merges and checkpoint serialization."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.checkpointer.factory import build_checkpoint_serde
from app.graph.retry import io_node
from app.graph.state import Message, TraceEntry, merge_by_id
from app.nodes.persist import _trace_entry_to_row


@pytest.mark.parametrize("item", [Message(role="user", content="original"), TraceEntry(node="original")])
def test_checkpoint_preserves_reducer_identity(item):
    serde = build_checkpoint_serde()
    recovered = serde.loads_typed(serde.dumps_typed(item))
    assert recovered.id == item.id
    assert len(merge_by_id([item], [recovered])) == 1


async def test_two_failed_swap_selection_branches_merge_without_crashing(monkeypatch):
    from app.subgraphs.swap import graph as graph_module
    from app.subgraphs.swap import select_counterparty, select_ticker
    from app.tools.swap_client import SwapClientHttpx

    @io_node
    async def intent(state):
        return {"intent": "place_order_request"}

    @io_node
    async def extract(state):
        return {
            "place_params": {"orderList": [{"orderId": "H-20260922-0000000001"}]},
            "swap_counterparties": [{"sort": "A", "shortName": "测试对手"}],
            "quote_ticker_candidates": [{"orderId": "H-20260922-0000000001", "candidates": [
                {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
            ]}],
        }

    counterparty_model, ticker_model = MagicMock(), MagicMock()
    counterparty_call = AsyncMock(side_effect=ValueError("bad counterparty output"))
    ticker_call = AsyncMock(side_effect=ValueError("bad ticker output"))
    counterparty_model.with_structured_output.return_value.ainvoke = counterparty_call
    ticker_model.with_structured_output.return_value.ainvoke = ticker_call
    monkeypatch.setattr(graph_module, "swap_intent", intent)
    monkeypatch.setattr(graph_module, "build_place_graph", lambda: extract)
    # 故障恢复测试显式命中 LLM 分支，不依赖选择规则是否提前完成匹配。
    monkeypatch.setattr(select_counterparty, "counterparty_choice", lambda state: None)
    monkeypatch.setattr(select_ticker, "ticker_choice", lambda state: None)
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", lambda: counterparty_model)
    monkeypatch.setattr(select_ticker, "get_qwen_complex", lambda: ticker_model)
    submit = AsyncMock(side_effect=AssertionError("failed selections must not submit"))
    monkeypatch.setattr(graph_module, "swap_place_order_submit", submit)
    backend = AsyncMock()
    monkeypatch.setattr(SwapClientHttpx, "operate", backend)
    result = await graph_module.build_swap_graph().ainvoke({
        "raw_text": "另一个吧", "quote_content": "引用",
        "conversation_id": "failure-recovery", "room_id": "test-room",
        "user_id": "test-user", "message_id": 1,
    })
    assert result.get("error")
    nodes = {result["error"].node, *(e.node for e in result["error"].causes)}
    assert nodes == {"swap_select_counterparty", "swap_select_ticker"}
    counterparty_call.assert_awaited_once()
    ticker_call.assert_awaited_once()
    submit.assert_not_called()
    backend.assert_not_called()


def test_retry_exhausted_audit_row_is_error():
    row = _trace_entry_to_row(TraceEntry(node="read", decision="error:retry_exhausted"), 0, "m", "t")
    assert row[7] == "error"


def test_audit_persistence_runs_after_history_and_render():
    from app.graph.main import build_main_graph

    edges = set(build_main_graph().builder.edges)
    assert ("record_history", "persist") in edges
    assert ("persist", "__end__") in edges
