"""swap.hand_to_share 节点测试（mock LLM，不联网）。

4 个用例：正常换算 / 多条订单 / 无手数直接透传 / LLM 异常透传。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import hand_to_share as mod
from app.subgraphs.swap.hand_to_share import convert_hands_to_shares_batch
from app.subgraphs.swap.models import SwapHandToShareItemOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, returns: list[SwapHandToShareItemOutput]) -> None:
    """让 LLM 按顺序返回 returns 中的每一项。"""
    it = iter(returns)
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=lambda _: next(it)))
    )
    monkeypatch.setattr(mod, "get_qwen_structured", lambda: fake_llm)


@pytest.mark.asyncio
async def test_converts_hand_to_shares_for_single_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有手数的订单条目 → LLM 换算后 placeOrderQuantity 填充。"""
    _patch_llm(
        monkeypatch,
        [SwapHandToShareItemOutput(uniqueId="x", placeOrderQuantityHand=10, placeOrderQuantity=10000)],
    )

    items = [
        {"placeOrderWindCode": "600900.SH", "placeOrderQuantityHand": 10, "placeOrderQuantity": None}
    ]
    result = await convert_hands_to_shares_batch(items)

    assert len(result) == 1
    assert result[0]["placeOrderQuantity"] == 10000
    assert result[0]["placeOrderQuantityHand"] == 10


@pytest.mark.asyncio
async def test_converts_multiple_items_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多条订单 → 逐条调用 LLM，结果顺序一致。"""
    _patch_llm(
        monkeypatch,
        [
            SwapHandToShareItemOutput(uniqueId="a", placeOrderQuantityHand=5, placeOrderQuantity=500),
            SwapHandToShareItemOutput(uniqueId="b", placeOrderQuantityHand=20, placeOrderQuantity=20000),
        ],
    )

    items = [
        {"placeOrderWindCode": "00700.HK", "placeOrderQuantityHand": 5, "placeOrderQuantity": None},
        {"placeOrderWindCode": "600900.SH", "placeOrderQuantityHand": 20, "placeOrderQuantity": None},
    ]
    result = await convert_hands_to_shares_batch(items)

    assert result[0]["placeOrderQuantity"] == 500
    assert result[1]["placeOrderQuantity"] == 20000


@pytest.mark.asyncio
async def test_passthrough_when_no_hand_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 placeOrderQuantityHand → 直接透传，不调 LLM。"""
    call_count = 0

    async def _never_called(_):
        nonlocal call_count
        call_count += 1
        return SwapHandToShareItemOutput(uniqueId="x")

    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=_never_called))
    )
    monkeypatch.setattr(mod, "get_qwen_structured", lambda: fake_llm)

    items = [{"placeOrderWindCode": "600900.SH", "placeOrderQuantity": 1000, "placeOrderQuantityHand": None}]
    result = await convert_hands_to_shares_batch(items)

    assert call_count == 0
    assert result[0]["placeOrderQuantity"] == 1000


@pytest.mark.asyncio
async def test_llm_exception_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 抛异常 → 原值透传，不让主流程崩溃。"""
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
    )
    monkeypatch.setattr(mod, "get_qwen_structured", lambda: fake_llm)

    items = [
        {"placeOrderWindCode": "600519.SH", "placeOrderQuantityHand": 3, "placeOrderQuantity": None}
    ]
    result = await convert_hands_to_shares_batch(items)

    assert len(result) == 1
    assert result[0]["placeOrderQuantityHand"] == 3
    assert result[0]["placeOrderQuantity"] is None
