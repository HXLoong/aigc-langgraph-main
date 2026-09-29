"""期权提交只消费本次联合结果，不回填引用卡片的旧业务参数。"""
from __future__ import annotations

from typing import Any

from app.parsing.models import OptionInstruction
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_place import option_extract_place
from tests.request_support import run_request_nodes

ORDER_ID = "Q-20260928-1234567890"
QUOTE = f"期权订单\n单号：{ORDER_ID}\n标的代码：600519.SH\n名义本金：2,000,000\n建仓指令：限价20\n期限：3M"


def _state(raw: str, intent: str, increment: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造带明确来源的单次结果，历史仅作为旧值污染的检测输入。"""
    fields = [{"path": "orders.0.orderId", "origin": "quote", "text": ORDER_ID}]
    if increment:
        fields.extend({"path": f"orders.0.{key}", "origin": "raw", "text": raw} for key in increment)
    instruction = OptionInstruction.model_validate({
        "product_type": "option", "intent": intent, "confidence": 0.9,
        "orders": [{"orderId": ORDER_ID, **(increment or {})}], "fields": fields,
        "evidence": [{"origin": "raw", "text": raw}],
    })
    return {"raw_text": raw, "quote_content": QUOTE, "conversation_id": "joint-option",
        "message_id": 100, "room_id": "room", "user_id": "user",
        "parsed_instruction": instruction.model_dump(exclude_none=True, exclude_unset=True)}


async def test_confirmation_submits_only_selected_identity(monkeypatch) -> None:
    """普通确认由 Java 获取订单，不重建旧本金、价格或标的。"""
    requests = []

    async def operate(self, request):
        """拦截真实 DTO 后的出站参数，不替换业务组装。"""
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 0, "data": "Java confirmation", "msg": ""}

    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    update = await run_request_nodes(option_extract_confirm_place, _state("确认下单", "confirm_order"), "option")
    assert update.get("error") is None
    assert requests[0]["orderList"] == [{"orderId": ORDER_ID}]


async def test_parameter_update_preserves_only_current_increment(monkeypatch) -> None:
    """本次 POV 增量保留小数，旧卡片其它值不进入新请求。"""
    requests = []

    async def operate(self, request):
        """记录接口参数作为行为断言依据。"""
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 0, "data": "Java updated", "msg": ""}

    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    update = await run_request_nodes(option_extract_place, _state("POV7.5", "place_order_from_quote", {"povRatio": 7.5}), "option")
    assert update.get("error") is None
    assert requests[0]["orderList"] == [{"orderId": ORDER_ID, "povRatio": 7.5}]
