"""期权后端业务回复由后端全权生成，render 不增删内容。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.nodes.render import render


@pytest.mark.asyncio
class TestBackendReplyPassthrough:
    async def test_pool_rejection_is_not_modified(self) -> None:
        ticker = SimpleNamespace(
            wind_code="399006.SZ", ins_sht_desc="创业板指", from_goats=True
        )
        rejection = "399006.SZ不在标的池内，请联系对口销售或交易员。"
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": rejection,
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == rejection

    async def test_quote_not_exist_is_not_modified(self) -> None:
        ticker = SimpleNamespace(
            wind_code="000016.SH", ins_sht_desc="上证50", from_goats=True
        )
        rejection = "000016.SH报价不存在，请联系对口销售或交易员。"
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": rejection,
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == rejection

    async def test_no_tickers_no_augment(self) -> None:
        """无 tickers → 不附加（无识别可声明）。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [],
            "api_result": "标的不在池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == "标的不在池内。"

    async def test_normal_api_result_not_augmented(self) -> None:
        """正常的 api_result（含订单详情）不该被附加。"""
        ticker = SimpleNamespace(
            wind_code="600519.SH", ins_sht_desc="贵州茅台", from_goats=True
        )
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": "-----场外期权询价详情-----\n单号：Q-001\n标的：600519.SH",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == state["api_result"]

    async def test_dict_ticker_also_works(self) -> None:
        """ticker 是 dict 形式（state 序列化后）也能正确读字段。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [{"windCode": "399006.SZ", "insShtDesc": "创业板指"}],
            "api_result": "399006.SZ不在标的池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == state["api_result"]
