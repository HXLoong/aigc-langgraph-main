"""render 节点核心路径测试。"""
from __future__ import annotations

import pytest

from app.nodes.render import render

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
        "expected_action": "inquiry",
        "place_params": {"orderList": []},
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
    """option place_order_from_quote：expected_action=place 时
    product_type=option，render 不应产生'-----互换订单参数-----'。
    """
    state: dict = {
        "product_type": "option",
        "place_params": {
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
async def test_option_inquiry_without_backend_result_never_fabricates_quote() -> None:
    state: dict = {
        "product_type": "option",
        "intent": "new_inquiry",
        "tickers": [{"windCode": "300773.SZ", "insShtDesc": "拉卡拉"}],
        "expected_action": "inquiry",
        "place_params": {
            "orderList": [
                {
                    "stockCode": "300773.SZ",
                    "optionType": "欧式看涨",
                    "tenor": None,
                    "strikePercentage": 80.0,
                }
            ],
        },
    }

    update = await render(state)  # type: ignore[arg-type]
    reply = update["reply_text"]

    assert reply == "期权服务未返回有效结果，本次未生成报价，请稍后重试或联系交易员。"
    assert "6.9%" not in reply
    assert "场外期权询价详情" not in reply


@pytest.mark.asyncio
async def test_option_backend_result_has_priority_and_is_passed_through_exactly() -> None:
    card = "-----场外期权询价详情-----\n单号：Q-001\n期限：【待补充】"
    state: dict = {
        "product_type": "option",
        "intent": "new_inquiry",
        "tickers": [],
        "ticker_hitl_candidates": [
            {"keyword": "拉卡拉", "candidates": [{"windCode": "300773.SZ"}]}
        ],
        "expected_action": "inquiry",
        "place_params": {"orderList": []},
        "api_result": card,
    }

    update = await render(state)  # type: ignore[arg-type]

    assert update["reply_text"] == card


# ============================================================
# Bug9: close confirm (opt-001) render 无 confirmOrderNoList 处理 → reply 空
# ============================================================


@pytest.mark.asyncio
async def test_render_close_confirm_returns_reply() -> None:
    """close_confirm_close 写入 confirm.confirmOrderNoList 后，
    render 应生成包含"平仓"和订单号的回复，不得返回空。
    """
    state: dict = {
        "product_type": "option_close",
        "intent": "close_order_confirm",
        "confirm": {
            "action": "close",
            "confirmOrderNoList": ["CO-20260304-ABCD1234"],
        },
        "raw_text": "确认平仓 CO-20260304-ABCD1234",
    }
    update = await render(state)  # type: ignore[arg-type]
    reply = update.get("reply_text") or ""
    assert reply, "close confirm render 不得返回空 reply"
    assert "平仓" in reply or "确认" in reply, (
        f"回复应含'平仓'或'确认'，实际: {reply!r}"
    )


@pytest.mark.asyncio
async def test_render_swap_backend_result_has_priority_and_is_passed_through_exactly() -> None:
    """swap place 已调用 operate 时，后端卡片是用户回复的唯一来源。"""
    card = "-----互换下单确认-----\n订单号: H-20260910-0000000001\n后端原始内容"
    state: dict = {
        "product_type": "swap",
        "place_params": {
            "orderList": [{
                "placeOrderWindCode": "600519.SH",
                "placeOrderOrderDirection": "BUY",
            }],
        },
        "raw_text": "200万买入茅台",
        "api_result": card,
    }

    update = await render(state)  # type: ignore[arg-type]

    assert update["reply_text"] == card


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_reply"),
    [
        (
            "MissingBackendContextError",
            "请求信息不完整，暂时无法调用互换服务，请重新发送原消息或联系运营。",
        ),
        (
            "EmptyBackendResultError",
            "互换服务未返回有效结果，本次未生成业务回执，请稍后重试或联系交易员。",
        ),
    ],
)
async def test_render_swap_backend_error_never_fabricates_order_card(
    error_type: str,
    expected_reply: str,
) -> None:
    """operate 失败后只能返回系统提示，不能使用旧业务状态拼卡片。"""
    state: dict = {
        "product_type": "swap",
        "place_params": {
            "orderList": [{
                "placeOrderWindCode": "600519.SH",
                "placeOrderOrderDirection": "BUY",
            }],
        },
        "tickers": [],
        "ticker_hitl_candidates": [
            {"keyword": "茅台", "candidates": [{"windCode": "600519.SH"}]}
        ],
        "raw_text": "200万买入茅台",
        "error": {
            "node": "swap_place_order_submit",
            "type": error_type,
            "message": "swap backend error",
        },
    }

    update = await render(state)  # type: ignore[arg-type]

    assert update["reply_text"] == expected_reply
    assert "互换订单参数" not in update["reply_text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [
        "place_order_request",
        "confirm_order",
        "cancel_order_request",
        "confirm_cancel_order",
        "confirm_modify_order",
        "query_order_status",
    ],
)
async def test_render_swap_operate_intent_without_backend_result_never_fabricates_success(
    intent: str,
) -> None:
    """应调用 operate 的互换意图缺少结果时，只能返回技术失败提示。"""
    order_list = [{"orderId": "H-20260910-0000000001"}]
    state: dict = {
        "product_type": "swap",
        "intent": intent,
        "place_params": {"orderList": order_list},
        "confirm": {"action": "place", "orderList": order_list},
        "cancel_params": {"orderList": order_list},
        "query_filter": {"orderList": order_list},
    }

    update = await render(state)  # type: ignore[arg-type]

    assert update["reply_text"] == (
        "互换服务未返回有效结果，本次未生成业务回执，请稍后重试或联系交易员。"
    )
