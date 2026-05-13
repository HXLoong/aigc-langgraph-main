"""render 节点：option confirm 必须输出"期权"而非"互换"。

Round 7-11 eval trace 暴露：用户对 option 报价"确认下单"，render path 8b 命中
`confirm.get("orderList")` 后直接返回"互换订单已确认提交，订单已接收、等待交易员
审核。" —— 但产品是 option，词法错误。Judge 看到"互换"自然判失败。

修复：按 product_type 区分文案：option/option_close → "期权"；swap → "互换"。
"""
from __future__ import annotations

import pytest

from app.nodes.render import render


@pytest.mark.asyncio
class TestRenderConfirmByProduct:
    """confirm 回复按 product_type 区分期权/互换。"""

    async def test_option_confirm_says_option(self) -> None:
        """product=option + confirm.orderList → 含"期权"。"""
        state: dict = {
            "product_type": "option",
            "intent": "confirm_order",
            "confirm": {"action": "place", "orderList": [{"orderId": "Q-001"}]},
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "期权" in reply, f"option confirm 应含期权字样，实际: {reply!r}"
        assert "互换" not in reply, f"option confirm 不应含互换，实际: {reply!r}"

    async def test_swap_confirm_says_swap(self) -> None:
        """product=swap + confirm.orderList → 含"互换"（保留原行为）。"""
        state: dict = {
            "product_type": "swap",
            "intent": "confirm_order",
            "confirm": {"orderList": [{"orderId": "H-001"}]},
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "互换" in reply
