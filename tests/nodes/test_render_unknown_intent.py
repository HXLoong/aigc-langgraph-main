"""render 节点：known product + unknown_intent 时不应空回复。

Round 11 eval trace 暴露：用户在询价后输入乱字符（如 "123456789"），路由识别
product_type=option 但 option_intent 返回 unknown_intent，option_unknown 节点
只写 trace 不写 reply_text，render 也没有对应分支 → 最终 reply_text 为空，
"(无回复)" 让用户困惑且 Judge 直接判 0。

修复：render 增加分支 — product 已识别但 intent 是 unknown_intent → 输出
统一兜底文案（Settings.default_reply，现场可配）。
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.nodes.render import render
from app.tools.receipts import UNCERTAIN_REPLY


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
        assert reply

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
        assert reply

    async def test_known_intent_unchanged(self) -> None:
        """正常 intent 且无后端回执 → 不被 unknown 分支干扰，输出待核对提示。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "expected_action": "inquiry",
            "place_params": {"orderList": []},
            "tickers": [],
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update.get("reply_text") == UNCERTAIN_REPLY
        assert update["trace"][0].decision == "backend_no_result"
