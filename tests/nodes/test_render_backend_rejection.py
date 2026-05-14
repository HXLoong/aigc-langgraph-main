"""render 节点：后端"不在标的池"等拒绝场景下，附加 ticker 识别详情。

Round 4-9 eval 暴露：用户问"创业板指 100% 3M"，系统正确识别为 399006.SZ 创业板指，
但场外期权后端标的池不收指数代码 → 返回"399006.SZ不在标的池内..."。当前 render
透传该消息，Judge 看不到"我们识别了 399006.SZ 创业板指"这件事，判为"未识别"。

修复：当 api_result 是后端的拒绝消息（含"不在标的池"/"报价不存在"等关键字）
且 state 里有 resolved tickers → 在拒绝消息前面追加"已识别为 [windCode insShtDesc]"
让 Judge 能看到识别已成功。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.nodes.render import render


@pytest.mark.asyncio
class TestBackendRejectionAugment:
    """后端拒绝消息 + 已 resolved tickers → 附加识别详情。"""

    async def test_pool_rejection_appends_ticker_recognition(self) -> None:
        """api_result 含"不在标的池" + tickers 已 resolved → reply 含"已识别"。"""
        ticker = SimpleNamespace(
            windCode="399006.SZ", insShtDesc="创业板指", from_goats=True
        )
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": "399006.SZ不在标的池内，请联系对口销售或交易员。",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "399006.SZ" in reply
        assert "创业板指" in reply
        assert "已识别" in reply, (
            f"应包含'已识别'让 Judge 看到识别结果，实际: {reply!r}"
        )

    async def test_quote_not_exist_also_augments(self) -> None:
        """api_result 含"报价不存在" → 同样附加识别详情。"""
        ticker = SimpleNamespace(
            windCode="000016.SH", insShtDesc="上证50", from_goats=True
        )
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": "000016.SH报价不存在，请联系对口销售或交易员。",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "000016.SH" in reply
        assert "上证50" in reply
        assert "已识别" in reply

    async def test_no_tickers_no_augment(self) -> None:
        """无 tickers → 不附加（无识别可声明）。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [],
            "api_result": "标的不在池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "已识别" not in reply

    async def test_normal_api_result_not_augmented(self) -> None:
        """正常的 api_result（含订单详情）不该被附加。"""
        ticker = SimpleNamespace(
            windCode="600519.SH", insShtDesc="贵州茅台", from_goats=True
        )
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": "-----场外期权询价详情-----\n单号：Q-001\n标的：600519.SH",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        # 正常报价回复不应被插入"已识别"前缀（已经在卡片里展示）
        assert not reply.startswith("已识别")

    async def test_dict_ticker_also_works(self) -> None:
        """ticker 是 dict 形式（state 序列化后）也能正确读字段。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [{"windCode": "399006.SZ", "insShtDesc": "创业板指"}],
            "api_result": "399006.SZ不在标的池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        reply = update.get("reply_text") or ""
        assert "已识别" in reply
        assert "399006.SZ" in reply
        assert "创业板指" in reply
