"""平仓解析值经真实 DTO/HTTP 原样送 Java，回执不得由本地伪造。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.nodes.render import render
from app.subgraphs.close import backend
from app.subgraphs.close.place_close import close_place_close
from app.tools.option_client import OptionClientHttpx
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes

ORDER = "CO-20260921-ABCDEF12"


async def run(monkeypatch, raw, orders, response=None):
    """只替换外部 HTTP，字段锁定和提交装配仍走真实代码。"""
    sent = []

    def handle(request):
        """记录出站 DTO 并返回指定的 Java 回执。"""
        assert request.url.path == "/admin-api/financial-orders/operate"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response or {"code": 0, "data": "Java receipt"})

    monkeypatch.setattr(backend, "OptionClientHttpx", lambda: OptionClientHttpx(
        base_url="http://test", transport=httpx.MockTransport(handle), dry_run=False))
    result = await run_request_nodes(close_place_close, {"raw_text": raw, "conversation_id": "c", "message_id": 1,
        "room_id": "r", "user_id": "u", "parsed_instruction": instruction_data(
            "option_close", "close_order_request", raw, orders=orders)}, "close")
    return sent, result


@pytest.mark.parametrize("amount", ["0", "-10000", "800000", "9000000"])
async def test_amount_policy_is_delegated_to_java(monkeypatch, amount):
    """零、负数和超过持仓的金额都由 Java 判断，不能本地拒绝。"""
    sent, result = await run(monkeypatch, f"{ORDER} 平{amount}元", [
        {"orderId": ORDER, "closeOrderNotionalDelta": amount}])
    assert not result.get("error"), result
    assert sent[0]["closeOrderReqVO"]["closeOrderList"][0]["closeOrderNotionalDelta"] == amount


@pytest.mark.parametrize("ratio", [0, 12.566, 30, 101])
async def test_pov_precision_and_range_are_not_changed(monkeypatch, ratio):
    """比例数值不截断、不重算，也不由 LangGraph 判断可执行范围。"""
    sent, result = await run(monkeypatch, f"{ORDER} POV{ratio}", [
        {"orderId": ORDER, "closeOrderType": "POV", "closeOrderPovRatio": ratio}])
    assert not result.get("error"), result
    assert sent[0]["closeOrderReqVO"]["closeOrderList"][0]["closeOrderPovRatio"] == ratio


@pytest.mark.parametrize("mode", ["限价单", "TWAP"])
async def test_missing_execution_parameters_are_not_filled(monkeypatch, mode):
    """未提供的价格和时间不回填旧值，由 Java 提示或合并。"""
    sent, result = await run(monkeypatch, f"{ORDER} {mode}", [{"orderId": ORDER, "closeOrderType": mode}])
    assert not result.get("error"), result
    assert sent[0]["closeOrderReqVO"]["closeOrderList"] == [{"orderId": ORDER, "closeOrderType": mode}]


@pytest.mark.parametrize("code,reply,display", [
    (0, "正在处理，请勿重复提交", "正在处理，请勿重复提交"),
    (400, "Java业务拒绝", "Java业务拒绝"), (500, "原始异常", "交易指令服务暂不可用"),
])
async def test_java_reply_is_authoritative(monkeypatch, code, reply, display):
    """成功或拒绝按 Java 回执呈现，500 保留原始审计并使用统一文案。"""
    sent, result = await run(monkeypatch, f"{ORDER} 市价", [{"orderId": ORDER}],
        {"code": code, "data": reply if code == 0 else None, "msg": reply})
    assert len(sent) == 1
    assert result["api_code"] == code and result["api_result"] == reply
    assert (await render({**result, "product_type": "option_close"}))["reply_text"] == display
