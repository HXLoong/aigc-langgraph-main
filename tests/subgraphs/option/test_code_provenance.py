"""来源检查与已锁定字段在真正的 HTTP 出站边界继续有效。"""
import json

import httpx

from app.extraction.fields import FieldRecord
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.tools.option_client import OptionClientHttpx
from tests.joint_support import instruction_data


async def test_foreign_locked_identity_never_reaches_http(monkeypatch):
    """确认范围检查后也不能被旧锁换成另一笔订单。"""
    sent = []

    def response(request):
        """只观察真实客户端调用，正确行为是完全不触发。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "unexpected"})

    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: OptionClientHttpx(
        base_url="http://test", transport=httpx.MockTransport(response), dry_run=False))
    chosen, foreign = "Q-20260922-0000000001", "Q-20260922-0000000002"
    parsed = instruction_data("option", "confirm_order", "确认下单", orders=[{"orderId": chosen}], quote=chosen)
    result = await option_extract_confirm_place({"raw_text": "确认下单", "quote_content": chosen,
        "conversation_id": "c", "message_id": 1, "room_id": "r", "user_id": "u", "parsed_instruction": parsed,
        "field_records": {"option/parse.orderList.0.orderId": FieldRecord(value=foreign, source="user", locked=True)}})
    assert result.get("error") and not sent
