"""render 节点核心路径测试。"""
from __future__ import annotations

import pytest

from app.nodes.render import _ZERO_HIT_TMPL, render


# ============================================================
# Bug2: make_initial_state 默认值 tickers=[] / place_params={} 不应触发零命中
# ============================================================


@pytest.mark.asyncio
async def test_render_does_not_zero_match_with_default_empty_place_params() -> None:
    """option_close confirm 类意图：tickers=[] + place_params={} 是初始默认值，
    不代表"真正经历了 ticker 解析并 0 命中"，不应返回零命中提示。
    """
    state: dict = {
        "tickers": [],
        "place_params": {},
        "raw_text": "确认平仓 CO-20260304-ABCD1234",
    }
    update = await render(state)  # type: ignore[arg-type]
    reply = update.get("reply_text") or ""
    assert "无法识别" not in reply, f"不应返回零命中提示，实际: {reply!r}"


@pytest.mark.asyncio
async def test_render_zero_match_triggers_when_place_params_has_content() -> None:
    """place_params 有实质内容（真实 inquiry 路径）+ tickers=[] → 才触发零命中提示。"""
    state: dict = {
        "tickers": [],
        "place_params": {"expected_action": "inquiry", "orderList": []},
        "raw_text": "这个标的abc",
    }
    update = await render(state)  # type: ignore[arg-type]
    reply = update.get("reply_text") or ""
    assert "无法识别" in reply, f"应触发零命中提示，实际: {reply!r}"


# ============================================================
# Bug4: option place_order 不能走互换渲染分支
# ============================================================


@pytest.mark.asyncio
async def test_render_option_place_order_does_not_show_swap_params() -> None:
    """option place_order_from_quote：place_params.expected_action=place 时
    product_type=option，render 不应产生'-----互换订单参数-----'。
    """
    state: dict = {
        "product_type": "option",
        "place_params": {
            "expected_action": "place",
            "orderList": [{"stockCode": "600519.SH", "optionType": "看涨"}],
        },
        "raw_text": "200万，市价下单",
    }
    update = await render(state)  # type: ignore[arg-type]
    reply = update.get("reply_text") or ""
    assert "互换订单参数" not in reply, (
        f"option place_order 不应走互换渲染，实际: {reply!r}"
    )


@pytest.mark.asyncio
async def test_render_swap_place_order_still_shows_swap_params() -> None:
    """swap place：product_type=swap + place_params.expected_action=place → 仍应走互换渲染。"""
    state: dict = {
        "product_type": "swap",
        "place_params": {
            "expected_action": "place",
            "orderList": [{
                "placeOrderWindCode": "600519.SH",
                "placeOrderOrderDirection": "BUY",
            }],
        },
        "raw_text": "200万买入茅台",
    }
    update = await render(state)  # type: ignore[arg-type]
    reply = update.get("reply_text") or ""
    assert "互换订单参数" in reply, (
        f"swap place_order 应走互换渲染，实际: {reply!r}"
    )
