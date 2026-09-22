"""未知意图使用配置的引导；已知业务无回执时提示结果待核对。"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.nodes.render import render


@pytest.mark.asyncio
class TestRenderUnknownIntent:
    """known product_type + unknown_intent → 友好引导，不空回复。"""

    async def test_option_unknown_intent_gives_friendly_reply(self) -> None:
        """product_type=option + intent=unknown_intent → 非空友好引导。"""
        state: dict = {
            "product_type": "option",
            "intent": "unknown_intent",
            "raw_text": "123456789",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert reply, "unknown_intent 应有友好引导，不应留空"
        assert reply == get_settings().default_reply

    async def test_swap_unknown_intent_gives_friendly_reply(self) -> None:
        """product_type=swap + intent=unknown_intent → 同样有引导。"""
        state: dict = {
            "product_type": "swap",
            "intent": "unknown_intent",
            "raw_text": "abc",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert reply == get_settings().default_reply

    async def test_unknown_with_quote_reuses_prompt(self) -> None:
        """unknown_intent + 引用前序询价卡 → 引导用户补充原模板要求的参数。"""
        state: dict = {
            "product_type": "option",
            "intent": "unknown_intent",
            "raw_text": "什么意思",
            "quote_content": (
                "-----场外期权询价详情-----\n单号：Q-001\n名义本金：待补充\n"
                "请引用本消息补充【交易对手】【名义本金】【建仓指令】"
            ),
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert reply == get_settings().default_reply

    async def test_known_intent_without_receipt_requires_verification(self) -> None:
        """正常 intent 且无回执 → 结果待核对，空 tickers 不表示识别失败。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "expected_action": "inquiry",
            "place_params": {"orderList": []},
            "tickers": [],
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert reply == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
