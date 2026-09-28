"""规则无法确定产品时沿用会话提示，当前明确产品优先。"""
import pytest

from app.nodes.intent_route import intent_route


@pytest.mark.parametrize("raw,previous,expected", [
    ("确认下单", "swap", "swap"), ("200万", "option_close", "option_close"),
    ("随便说点什么完全无关的", None, "unknown"), ("呵呵", "unknown", "unknown"),
    ("买入 贵州茅台 10000股 POV 20%", "option", "swap"),
])
async def test_previous_product_only_fills_rule_ambiguity(raw, previous, expected):
    """产品提示只改变所选解析契约，不在本节点再次调用模型。"""
    result = await intent_route({"raw_text": raw, "product_type": previous})
    assert result["product_type"] == expected


def test_turn_input_preserves_product_context():
    """输入映射不覆盖 checkpoint 中的上轮产品提示。"""
    from app.api.turn_state import inputs_to_state

    assert "product_type" not in inputs_to_state({"rawContent": "确认下单"})
