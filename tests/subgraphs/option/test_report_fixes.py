"""多订单补参保留每笔显式增量，不再回填引用卡片字段。"""
from unittest.mock import AsyncMock, Mock

from app.llm.clients import _ChatLLM
from app.subgraphs.option.extract_place import option_extract_place
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes

Q1, Q2 = "Q-20260920-9894130688", "Q-20260920-2309752320"
QUOTE = f"序号：1\n单号：{Q1}\n期限：1M\n序号：2\n单号：{Q2}\n期限：2M"


async def test_batch_increment_keeps_order_identity_without_old_fields(monkeypatch):
    """模型已经给出各笔结果，子图不再调用模型或重建旧订单。"""
    model = Mock(side_effect=AssertionError("子图不允许模型调用"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", model)
    client = Mock(operate=AsyncMock(return_value={"code": 0, "data": "Java批量补参回执"}))
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    raw = "第1笔200万限价10；第2笔100万限价6"
    orders = [{"orderId": Q1, "notionalAmount": "2000000", "limitPrice": 10},
              {"orderId": Q2, "notionalAmount": "1000000", "limitPrice": 6}]
    result = await run_request_nodes(option_extract_place, {"raw_text": raw, "quote_content": QUOTE,
        "conversation_id": "c", "message_id": 1, "user_id": "u", "room_id": "r",
        "parsed_instruction": instruction_data("option", "place_order_from_quote", raw,
                                               orders=orders, quote=QUOTE)}, "option")
    assert not result.get("error"), result
    request = client.operate.await_args.args[0].model_dump(mode="json", by_alias=True, exclude_none=True)
    assert request["orderList"] == orders
    assert result["api_result"] == "Java批量补参回执"
    model.assert_not_called()
