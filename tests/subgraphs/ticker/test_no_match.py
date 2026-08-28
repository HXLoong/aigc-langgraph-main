"""ticker 0 命中 fallback 测试（Issue #30）。

验证：
- resolver 0 命中时降级白名单，tickers 可能为空
- swap.place_order 节点能 graceful 处理 tickers=[]
- 全工具 mock 返回空时 resolve_ticker_full 正常返回（不卡 recursion_limit）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import place_order as place_order_mod
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution

_ZERO_MATCH_RESOLUTION = TickerResolution(resolved=[], hitl_pending=[])


def _patch_place_order_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_params = SwapPlaceOrderParams(orderList=[SwapOrderItem(placeOrderWindCode="XYZ123")])
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(return_value=fake_params))
    )
    monkeypatch.setattr(place_order_mod, "get_qwen_complex", lambda: fake_llm)


@pytest.mark.asyncio
async def test_zero_match_resolver_returns_empty_tickers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 命中 → tickers=[]，state 无 ticker_hitl_candidates。"""
    _patch_place_order_llm(monkeypatch)
    monkeypatch.setattr(
        place_order_mod, "resolve_ticker_full", AsyncMock(return_value=_ZERO_MATCH_RESOLUTION)
    )

    result = await place_order_mod.swap_place_order({"raw_text": "XYZ123这个标的"})

    assert result.get("tickers") == []
    assert "ticker_hitl_candidates" not in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_zero_match_trace_records_zero_tickers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 命中时 trace 里 tickers_count=0，hitl_count=0。"""
    _patch_place_order_llm(monkeypatch)
    monkeypatch.setattr(
        place_order_mod, "resolve_ticker_full", AsyncMock(return_value=_ZERO_MATCH_RESOLUTION)
    )

    result = await place_order_mod.swap_place_order({"raw_text": "XYZ123这个标的"})

    entry = next(
        (e for e in result.get("trace", []) if e.node == "swap_place_order"), None
    )
    assert entry is not None
    assert entry.llm_output is not None
    assert entry.llm_output.get("tickers_count") == 0
    assert entry.llm_output.get("hitl_count") == 0


@pytest.mark.asyncio
async def test_resolve_ticker_full_returns_empty_not_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_ticker_full 后端 + LLM 均 0 命中时返回 empty resolution，不抛异常。"""
    from unittest.mock import AsyncMock, MagicMock

    import app.subgraphs.ticker.resolver as res_mod
    import app.subgraphs.ticker.tools as tools_mod

    client = MagicMock()
    client.search_securities_instrument = AsyncMock(return_value=[])
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    monkeypatch.setattr(res_mod, "_make_client", lambda: client)

    # 3 路批量 LLM 全部返回空 dict：候选无法解析出任何 org item，管线在
    # merge_and_validate 前即无 GOATS 查询目标，属于 0 命中的合法路径之一。
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content=""))
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: fake_llm)

    from app.subgraphs.ticker.resolver import resolve_ticker_full

    resolution = await resolve_ticker_full("这是一个肯定不存在的乱码标的XYZNOMATCH9999")

    assert resolution.resolved == []
    assert resolution.hitl_pending == []
