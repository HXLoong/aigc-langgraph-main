"""render 节点：平仓申请卡输出完整字段（治 opt-078~097 的"参数遗漏"扣分）。

Round H eval 暴露：18+ option_close case 平仓卡只输出
"平仓申请已生成，请确认后回复【确认平仓】"，Judge 期望含：
合约编号 / 单号 / 申请时间 / 期权类型 / 标的代码 / 标的名称
→ 扣 0.2-0.3 分（实际多个 case 卡在 0.7-0.8）。

修复：close.closeOrderList 触发时，渲染完整字段卡。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.nodes.render import render


@pytest.mark.asyncio
class TestCloseCardEnriched:
    """平仓申请卡完整字段渲染。"""

    async def test_close_card_contains_orderId(self) -> None:
        """closeOrderList[0].orderId → 卡里有单号字段。"""
        state: dict = {
            "product_type": "option_close",
            "intent": "close_order_request",
            "close_params": {
                "closeOrderList": [{
                    "orderId": "OPT-20260514-0001",
                    "closeOrderNotionalDelta": "1000000",
                    "closeOrderType": "市价单",
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "OPT-20260514-0001" in reply, f"应含订单号: {reply!r}"
        assert "单号" in reply or "合约编号" in reply

    async def test_close_card_contains_ticker_info(self) -> None:
        """state.tickers → 卡里有标的代码 + 名称。"""
        state: dict = {
            "product_type": "option_close",
            "intent": "close_order_request",
            "tickers": [SimpleNamespace(windCode="600519.SH", insShtDesc="贵州茅台")],
            "close_params": {
                "closeOrderList": [{
                    "orderId": "OPT-20260514-0002",
                    "closeOrderNotionalDelta": "全部",
                }],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "600519.SH" in reply, f"应含标的代码: {reply!r}"
        assert "贵州茅台" in reply

    async def test_close_card_extracts_option_type_from_quote(self) -> None:
        """quote_content 含期权类型描述 → 卡里有期权类型。"""
        state: dict = {
            "product_type": "option_close",
            "intent": "close_order_request",
            "quote_content": "Q-20260513-9999 欧式看涨 1M 80% ...",
            "close_params": {
                "closeOrderList": [{"orderId": "OPT-20260514-0003"}],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "欧式看涨" in reply or "期权类型" in reply

    async def test_close_card_keeps_action_prompt(self) -> None:
        """卡末尾仍提示用户回复【确认平仓】。"""
        state: dict = {
            "product_type": "option_close",
            "intent": "close_order_request",
            "close_params": {
                "closeOrderList": [{"orderId": "OPT-20260514-0004"}],
            },
        }
        reply = (await render(state)).get("reply_text") or ""
        assert "确认平仓" in reply
