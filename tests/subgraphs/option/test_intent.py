"""期权入口消费联合意图并验证来源，语义准确率由意图数据集评估。"""
from __future__ import annotations

import pytest

from app.subgraphs.option.intent import option_intent
from tests.joint_support import instruction_data


@pytest.mark.parametrize("intent", ["new_inquiry", "place_order_from_quote", "confirm_order", "request_cancel_order", "unknown_intent"])
async def test_consumes_current_joint_result(intent: str) -> None:
    """每个意图复用当前结果，不再调用独立模型分类。"""
    raw = "本次期权指令"
    state = {"raw_text": raw, "parsed_instruction": instruction_data("option", intent, raw)}
    update = await option_intent(state)
    assert update.get("error") is None and update["intent"] == intent
    assert update["trace"][0].decision == f"parsed→{intent}"


async def test_missing_joint_result_stops_before_business() -> None:
    """独立执行必须提供上游结果，不能隐藏地重跑解析。"""
    update = await option_intent({"raw_text": "确认下单"})
    assert update["error"].code == "E2"


async def test_fabricated_intent_source_is_rejected() -> None:
    """有结构化结果也必须能追溯到本轮输入。"""
    update = await option_intent({"raw_text": "真实输入", "parsed_instruction": instruction_data("option", "confirm_order", "伪造来源")})
    assert update["error"].code == "E2"
