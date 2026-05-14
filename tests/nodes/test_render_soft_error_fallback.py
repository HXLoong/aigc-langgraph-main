"""render 节点：后端返回"正在处理 / 请勿重复"等软错误时，回退到本地订单卡渲染。

Round 40-case eval 暴露：option 多轮 confirm 流程下，后端会偶发返回
"正在处理，请勿重复提交"（受 conversationId + 高频请求 dedup 影响）。
当前 render 透传该消息 → Judge 看到"机器人未执行下单"判 0 分。

修复策略：检测软错误关键词时，**不**透传 api_result；优先用 place_params
本地渲染订单卡，让用户看到我们识别的下单参数。
"""
from __future__ import annotations

import pytest

from app.nodes.render import render


SOFT_ERROR_MARKERS = ("正在处理", "请勿重复")


@pytest.mark.asyncio
class TestSoftErrorFallback:
    """软错误回退：api_result 含'正在处理'时不透传给用户。"""

    async def test_option_place_soft_error_falls_back_to_inquiry_card(self) -> None:
        """option place_order_from_quote + 软错误 → 渲染期权询价/订单卡，不透传'正在处理'。"""
        state: dict = {
            "product_type": "option",
            "intent": "place_order_from_quote",
            "api_result": "正在处理，请勿重复提交",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "stockCode": "600519.SH",
                    "optionType": "欧式看涨",
                    "tenor": "1M",
                    "strikePercentage": 80,
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "正在处理" not in reply, f"软错误不应透传给用户：{reply!r}"
        assert "请勿重复" not in reply
        # 至少应有产品参数提示
        assert any(kw in reply for kw in ("600519", "欧式看涨", "交易对手", "本金")), (
            f"应包含订单参数信息：{reply!r}"
        )

    async def test_swap_place_soft_error_falls_back_to_swap_card(self) -> None:
        """swap place_order + 软错误 → 渲染互换订单卡（13 字段模板），不透传'正在处理'。"""
        state: dict = {
            "product_type": "swap",
            "intent": "place_order_request",
            "raw_text": "深港通1357.HK 买入1000股 18 11125测试短名",
            "api_result": "正在处理，请勿重复提交",
            "place_params": {
                "expected_action": "place",
                "orderList": [{
                    "placeOrderWindCode": "1357.HK",
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderQuantity": 1000,
                    "placeOrderPrice": 18,
                    "placeOrderPriceType": "LimitOrder",
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "正在处理" not in reply
        assert "1357.HK" in reply
        assert "买入" in reply

    async def test_normal_api_result_still_passes_through(self) -> None:
        """非软错误的 api_result 仍正常透传（不影响成功路径）。"""
        state: dict = {
            "product_type": "option",
            "intent": "place_order_from_quote",
            "api_result": "期权订单已确认提交，订单号: Q-20260514-1234567890",
            "place_params": {},
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "期权订单已确认提交" in reply
