"""平仓入口只验证并消费联合意图，保留产品与来源边界。"""
from __future__ import annotations

import pytest

from app.subgraphs.close.intent import close_intent
from tests.joint_support import instruction_data


@pytest.mark.parametrize("intent", ["close_order_query", "close_order_request", "close_order_confirm", "close_order_cancel_request", "close_order_cancel_confirm", "close_order_order_query"])
async def test_close_intent_uses_joint_result(intent: str) -> None:
    """按已识别动作分发，不以代码补参或历史状态改变本次动作。"""
    raw = "本次平仓指令"
    data = instruction_data("option_close", intent, raw)
    update = await close_intent({"raw_text": raw, "parsed_instruction": data})
    assert update.get("error") is None and update["intent"] == intent


async def test_foreign_product_is_not_accepted_by_close_graph() -> None:
    """跨产品结果必须由主图路由，平仓子图不擅自重分类。"""
    update = await close_intent({"raw_text": "查询", "parsed_instruction": instruction_data("option", "query_order_status", "查询")})
    assert update["error"].code == "E2"
