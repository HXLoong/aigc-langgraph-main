"""互换入口消费唯一解析结果，子图内不重复调用模型。"""
from __future__ import annotations

import pytest

from app.subgraphs.swap.intent import swap_intent
from tests.joint_support import instruction_data


@pytest.mark.parametrize("intent", ["place_order_request", "cancel_order_request", "confirm_order", "confirm_modify_order", "confirm_cancel_order", "query_order_status"])
async def test_swap_intent_uses_joint_result(intent: str) -> None:
    """用户本次动作作为独立输入，普通动作不提升为确认。"""
    raw = "本次互换指令"
    update = await swap_intent({"raw_text": raw, "parsed_instruction": instruction_data("swap", intent, raw)})
    assert update.get("error") is None and update["intent"] == intent


async def test_stale_evidence_stops_intent_dispatch() -> None:
    """前一轮原文不能冒充本次动作的证据。"""
    update = await swap_intent({"raw_text": "本轮消息", "parsed_instruction": instruction_data("swap", "confirm_order", "上轮消息")})
    assert update["error"].code == "E2"
