"""平仓内部图仅准备、检查、提交，模型和只读上下文准备均在上游。"""
from unittest.mock import AsyncMock, MagicMock

from app.llm.clients import _ChatLLM
from app.subgraphs.close.place_close import build_place_close_graph, close_place_close
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes


def test_private_intermediate_fields_do_not_escape():
    """原生子图只写回公共业务对象，私有准备参数不污染主图。"""
    graph = build_place_close_graph()
    assert set(graph.get_graph().nodes) == {"__start__", "place_close_prepare", "place_close_validate", "place_close_submit", "__end__"}
    assert not any(key.startswith("pc_") for key in graph.output_channels)
    assert not {"raw_text", "history_messages", "product_type"}.intersection(graph.output_channels)


async def test_each_stage_is_traced_and_java_called_once(monkeypatch):
    """内部图不再查上下文或调用模型，提交值保持提取结果。"""
    no_model = MagicMock(side_effect=AssertionError("内部图不可调用模型"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", no_model)
    query = AsyncMock(side_effect=AssertionError("上下文在主图解析前读取"))
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.query_close_orders", query)
    backend = AsyncMock(return_value={"code": 0, "data": "Java receipt"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    raw = "OPT-AAAA1 平200万市价"
    orders = [{"internalTradeId": "OPT-AAAA1", "closeOrderNotionalDelta": "2000000", "closeOrderType": "市价单"}]
    result = await run_request_nodes(close_place_close, {"raw_text": raw, "conversation_id": "c", "room_id": "r",
        "user_id": "u", "message_id": 1, "parsed_instruction": instruction_data(
            "option_close", "close_order_request", raw, orders=orders)}, "close")
    assert not result.get("error"), result
    assert [entry.node for entry in result["trace"]] == ["place_close_prepare", "place_close_validate", "place_close_submit", "close_clean_request", "close_submit"]
    assert backend.await_count == 1 and result["api_result"] == "Java receipt"
    assert backend.await_args.args[0].model_dump(exclude_none=True)["closeOrderReqVO"]["closeOrderList"] == orders
    query.assert_not_called()
    no_model.assert_not_called()


async def test_bad_source_stops_before_java(monkeypatch):
    """错误来源归因于参数准备，后续阶段不再执行。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    parsed = instruction_data("option_close", "close_order_request", "伪造原文", orders=[{"internalTradeId": "OPT-AAAA1"}])
    result = await run_request_nodes(close_place_close, {"raw_text": "平仓", "parsed_instruction": parsed}, "close")
    assert result["error"].node == "place_close_prepare"
    backend.assert_not_called()
