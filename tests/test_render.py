"""Java 负责业务卡片与标的结果；render 负责透传、展示投影及兜底。"""
from copy import deepcopy

import pytest

from app.config import get_settings
from app.graph.state import ErrorInfo
from app.nodes.render import render


@pytest.mark.asyncio
async def test_backend_disambiguation_card_is_passed_through():
    receipt = "  候选标的：\r\n1. 00700.HK 腾讯控股\n2. TME.N 腾讯音乐\n"
    state = {"product_type": "option", "intent": "new_inquiry", "api_code": 0,
             "api_result": receipt, "ticker_hitl_candidates": [
                 {"keyword": "旧候选", "candidates": [{"windCode": "STALE.CODE"}]}]}
    original = deepcopy(state)
    assert (await render(state))["reply_text"] == receipt
    assert state == original


@pytest.mark.asyncio
async def test_multiple_local_candidate_groups_do_not_create_card():
    state = {"product_type": "option", "intent": "new_inquiry", "ticker_hitl_candidates": [
        {"keyword": "A", "candidates": [{"windCode": "A1.SH"}, {"windCode": "A2.SH"}]},
        {"keyword": "B", "candidates": [{"windCode": "B1.HK"}, {"windCode": "B2.HK"}]},
    ]}
    original = deepcopy(state)
    reply = (await render(state))["reply_text"]
    assert reply == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
    assert all(code not in reply for code in ("A1.SH", "A2.SH", "B1.HK", "B2.HK"))
    assert state == original


@pytest.mark.asyncio
async def test_empty_tickers_do_not_claim_zero_matches():
    result = await render({"product_type": "option", "intent": "new_inquiry", "tickers": [],
                           "place_params": {"orderList": []}, "raw_text": "神秘标的XYZ"})
    assert result["reply_text"] == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
    assert "无法识别" not in result["reply_text"]


@pytest.mark.asyncio
async def test_empty_state_uses_configured_guidance():
    result = await render({"tickers": []})
    assert result["reply_text"] == get_settings().default_reply


@pytest.mark.asyncio
async def test_error_state_uses_configured_guidance():
    state = {"error": ErrorInfo(node="swap_place_order", type="ValueError", message="something went wrong")}
    original = deepcopy(state)
    assert (await render(state))["reply_text"] == get_settings().default_reply
    assert state == original


@pytest.mark.asyncio
async def test_swap_without_backend_result_does_not_assert_trade_outcome():
    state = {"product_type": "swap", "intent": "place_order_request",
             "place_params": {"orderList": [{"orderId": "H-LOCAL", "placeOrderQuantity": 1000}]}}
    reply = (await render(state))["reply_text"]
    assert reply == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
    assert "H-LOCAL" not in reply and "1000" not in reply


@pytest.mark.asyncio
async def test_backend_rejection_has_priority_over_legacy_candidate_fields():
    receipt = "该标的不在交易范围内，请联系交易员。\n"
    state = {"product_type": "option", "intent": "new_inquiry", "api_code": 400,
             "api_result": receipt, "tickers": [], "ticker_hitl_candidates": [
                 {"keyword": "腾讯", "candidates": [{"windCode": "00700.HK"}]}]}
    original = deepcopy(state)
    assert (await render(state))["reply_text"] == receipt
    assert state == original
