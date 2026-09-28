"""询价内部图是准备、来源检查、Java提交三个确定性阶段。"""
from unittest.mock import AsyncMock

from app.subgraphs.option.extract_inquiry import build_inquiry_graph, option_extract_inquiry
from tests.joint_support import instruction_data


def test_topology_and_output_boundary():
    """内部参数不写回父图，会话历史也不由子图重复输出。"""
    graph = build_inquiry_graph()
    assert set(graph.get_graph().nodes) == {"__start__", "inquiry_prepare", "inquiry_validate", "inquiry_submit", "__end__"}
    assert not any(key.startswith("iq_") for key in graph.output_channels)
    assert "history_messages" not in graph.output_channels


async def test_source_failure_is_attributed_before_submit(monkeypatch):
    """即使 typed 值合法，证据不在原文也不能提交。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    parsed = instruction_data("option", "new_inquiry", "期权询价", orders=[{"stockCode": "伪造证券"}])
    parsed["fields"][0]["text"] = "伪造证券"
    result = await option_extract_inquiry({"raw_text": "期权询价", "parsed_instruction": parsed})
    assert result["error"].node == "inquiry_validate"
    assert [entry.node for entry in result["trace"]] == ["inquiry_prepare", "inquiry_validate"]
    backend.assert_not_called()
