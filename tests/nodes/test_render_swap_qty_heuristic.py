"""swap render 数量/价格 启发式纠正回归测试。

Round 14 暴露：LLM 容易把"X元 + 小数字"误判为"数量 = 小数字"。修复用启发式：
notional / price / qty 之间的数量级关系判断是否需要 swap。

回归保护：
- 真正的小数量（< 10000）+ 小金额（数量级匹配）不触发 swap
- 大数量（>= 10000）即使有 notional 也不触发 swap
"""
from __future__ import annotations

import pytest

from app.nodes.render import render


@pytest.mark.asyncio
class TestSwapQtyHeuristic:
    """数量/价格 启发式纠正与保护。"""

    async def test_yuan_notional_small_qty_swap(self) -> None:
        """X元 + 小 qty → swap (qty becomes price, recompute qty)。"""
        state: dict = {
            "product_type": "swap",
            "raw_text": "沪港通00388.HK 买入80000元 280 11125测试短名（张天琪专用）",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "placeOrderWindCode": "00388.HK",
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderQuantity": 280,
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "限定价格: 280" in reply
        assert "委托金额: 80,000.00" in reply
        # 数量推算 80000/280 ≈ 285
        assert "数量: 285股" in reply or "数量: 286股" in reply

    async def test_qty_missing_derive_from_notional_price(self) -> None:
        """qty 缺失 + notional + price → qty = notional / price。"""
        state: dict = {
            "product_type": "swap",
            "raw_text": "深港通1357.HK 卖出78000HKD 限价19.50",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "placeOrderWindCode": "1357.HK",
                    "placeOrderOrderDirection": "SELL",
                    "placeOrderPrice": 19.50,
                    "placeOrderPriceType": "LimitOrder",
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        # 78000 / 19.50 = 4000
        assert "数量: 4000股" in reply
        assert "限定价格: 19.5" in reply

    async def test_large_qty_not_swapped(self) -> None:
        """qty >= 10000 不应触发 swap（用户真给大数量场景）。"""
        state: dict = {
            "product_type": "swap",
            "raw_text": "600519.SH 买入200000元 18.12 100000股",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "placeOrderWindCode": "600519.SH",
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderQuantity": 100000,
                    "placeOrderPrice": 18.12,
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        # qty 保留 100000
        assert "数量: 100000股" in reply
        assert "限定价格: 18.12" in reply

    async def test_no_notional_no_swap(self) -> None:
        """无 notional 信号 → 不触发 swap。"""
        state: dict = {
            "product_type": "swap",
            "raw_text": "600519.SH 买入50股",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "placeOrderWindCode": "600519.SH",
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderQuantity": 50,
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        # qty 保留 50（不动）
        assert "数量: 50股" in reply
