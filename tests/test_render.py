"""render 节点测试（Issue #20）。

覆盖三路输出：
1. ticker_hitl_candidates → 消歧卡片
2. tickers==[] + place_params → 0 命中提示
3. error → 通用兜底
4. 正常路径 → 不写 reply_text
"""
from __future__ import annotations

import pytest

from app.graph.state import ErrorInfo
from app.nodes.render import render


def _state(**kw):
    return kw


# ============================================================
# 1. HITL 消歧卡片
# ============================================================


@pytest.mark.asyncio
async def test_hitl_candidates_produce_card() -> None:
    state = _state(
        ticker_hitl_candidates=[
            {
                "keyword": "腾讯",
                "candidates": [
                    {"windCode": "00700.HK", "insShtDesc": "腾讯控股"},
                    {"windCode": "TME.N", "insShtDesc": "腾讯音乐"},
                ],
            }
        ]
    )
    result = await render(state)
    assert "reply_text" in result
    text = result["reply_text"]
    assert "腾讯" in text
    assert "00700.HK" in text
    assert "TME.N" in text


@pytest.mark.asyncio
async def test_hitl_multiple_keywords() -> None:
    state = _state(
        ticker_hitl_candidates=[
            {
                "keyword": "A",
                "candidates": [
                    {"windCode": "A1.SH", "insShtDesc": "甲"},
                    {"windCode": "A2.SH", "insShtDesc": "乙"},
                ],
            },
            {
                "keyword": "B",
                "candidates": [
                    {"windCode": "B1.HK", "insShtDesc": "丙"},
                    {"windCode": "B2.HK", "insShtDesc": "丁"},
                ],
            },
        ]
    )
    result = await render(state)
    text = result["reply_text"]
    assert "A1.SH" in text
    assert "B1.HK" in text


# ============================================================
# 2. 0 命中 → 友好提示
# ============================================================


@pytest.mark.asyncio
async def test_zero_tickers_with_place_params_produces_hint() -> None:
    state = _state(
        tickers=[],
        place_params={"expected_action": "place", "orderList": []},
        raw_text="帮我买个神秘标的XYZ",
    )
    result = await render(state)
    assert "reply_text" in result
    text = result["reply_text"]
    assert "无法识别" in text or "抱歉" in text
    assert "神秘标的" in text or "XYZ" in text or "标准" in text


@pytest.mark.asyncio
async def test_zero_tickers_without_place_params_no_reply() -> None:
    """tickers=[] 但无 place_params（不是下单场景）→ 不产生 reply_text。"""
    state = _state(tickers=[])
    result = await render(state)
    assert "reply_text" not in result or result.get("reply_text") is None


# ============================================================
# 3. error → 通用兜底
# ============================================================


@pytest.mark.asyncio
async def test_error_state_produces_fallback_reply() -> None:
    state = _state(
        error=ErrorInfo(
            node="swap_place_order",
            type="ValueError",
            message="something went wrong",
        )
    )
    result = await render(state)
    assert "reply_text" in result
    assert "换种说法" in result["reply_text"] or "理解" in result["reply_text"]


# ============================================================
# 4. 正常路径 → 不干预
# ============================================================


@pytest.mark.asyncio
async def test_normal_path_no_reply_text() -> None:
    from app.graph.state import TickerCandidate

    state = _state(
        intent="place_order_request",
        product_type="swap",
        tickers=[TickerCandidate(windCode="600519.SH", insShtDesc="贵州茅台", from_goats=True)],
        place_params={"expected_action": "place", "orderList": []},
    )
    result = await render(state)
    assert not result.get("reply_text")


# ============================================================
# 5. HITL 优先级高于 0 命中
# ============================================================


@pytest.mark.asyncio
async def test_hitl_takes_priority_over_zero_tickers() -> None:
    """同时有 hitl_candidates 和 tickers=[] → 输出消歧卡片（HITL 优先）。"""
    state = _state(
        ticker_hitl_candidates=[
            {
                "keyword": "腾讯",
                "candidates": [
                    {"windCode": "00700.HK", "insShtDesc": "腾讯控股"},
                    {"windCode": "TME.N", "insShtDesc": "腾讯音乐"},
                ],
            }
        ],
        tickers=[],
        place_params={"expected_action": "inquiry", "orderList": []},
    )
    result = await render(state)
    assert "00700.HK" in result["reply_text"]
