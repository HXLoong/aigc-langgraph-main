"""隔离 LLM 与 HTTP，验证平仓识别结果进入真实客户端且回执不被本地规则替换。"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.nodes.render import render
from app.subgraphs.close import place_close as pc
from app.subgraphs.close.execution_fragments import split_execution_fragments
from app.subgraphs.close.models import CloseOrderItem
from app.subgraphs.close.normalization import normalize_holding_candidates
from app.tools.option_client import OptionClientHttpx
from tests.subgraphs.close.candidate_fixtures import close_candidates, holding_candidates

ORDER = "CO-20260921-ABCDEF12"
SECOND = "CO-20260921-ABCDEF34"


def _isolate(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    *,
    response: dict[str, Any] | None = None,
    holdings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query-close-orders"):
            return httpx.Response(200, json={"code": 0, "data": holdings or []})
        assert request.url.path == "/admin-api/financial-orders/operate"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response or {"code": 0, "data": "Java确认卡"})

    transport = httpx.MockTransport(handle)

    def client() -> OptionClientHttpx:
        return OptionClientHttpx(base_url="http://option.test", transport=transport, dry_run=False)

    for target in (
        "app.subgraphs.close.place_close.OptionClientHttpx",
        "app.subgraphs.close.backend.OptionClientHttpx",
    ):
        monkeypatch.setattr(target, client)
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=close_candidates(*rows),
    )
    monkeypatch.setattr(pc, "get_qwen_thinking", lambda: llm)
    return sent


async def _run(raw: str) -> dict[str, Any]:
    return await pc.close_place_close({
        "raw_text": raw, "conversation_id": "boundary-test", "message_id": 1,
        "room_id": "test-room", "user_id": "test-user",
    })


@pytest.mark.parametrize("amount,available", [("80万", 800000), ("0", 800000), ("-1万", 800000)])
async def test_amount_policy_is_delegated_to_java(monkeypatch, amount, available):
    reply = "Java返回的全仓确认或金额校验提示"
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "closeOrderType": "市价",
                                  "closeOrderNotionalDelta": amount}],
                    response={"code": 0, "data": reply},
                    holdings=[{"orderId": ORDER, "availableNotional": available}])
    result = await _run(f"{ORDER} {amount} 市价")
    assert result.get("error") is None
    assert len(sent) == 1
    expected = {"80万": "800000", "0": "0", "-1万": "-10000"}[amount]
    assert sent[0]["closeOrderReqVO"]["closeOrderList"][0]["closeOrderNotionalDelta"] == expected
    shown = await render({**result, "product_type": "option_close"})
    assert shown["reply_text"] == reply


@pytest.mark.parametrize("ratio", ["12.566", "0", "30", "101"])
async def test_pov_number_reaches_http_without_local_policy(monkeypatch, ratio):
    reply = "Java的POV校验结果"
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "closeOrderType": f"POV{ratio}"}],
                    response={"code": 400, "msg": reply})
    result = await _run(f"{ORDER} POV{ratio}")
    assert result.get("error") is None
    assert len(sent) == 1
    value = sent[0]["closeOrderReqVO"]["closeOrderList"][0]["closeOrderPovRatio"]
    assert isinstance(value, (int, float)) and value == float(ratio)
    assert result["field_records"]["close/place_close.orderList.0.closeOrderPovRatio"].value == value
    assert (await render({**result, "product_type": "option_close"}))["reply_text"] == reply


async def test_missing_limit_is_sent_for_backend_merge(monkeypatch):
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "closeOrderType": "限价"}],
                    holdings=[{"orderId": ORDER, "closeOrderPrice": 10}])
    result = await _run(f"{ORDER} 限价")
    assert result.get("error") is None
    assert len(sent) == 1
    assert sent[0]["closeOrderReqVO"]["closeOrderList"][0].get("closeOrderPrice") is None
    assert not result.get("reply_text")


@pytest.mark.parametrize("raw", ["TWAP", "TWAP20分钟"])
async def test_extracted_twap_without_times_uses_backend_defaults(monkeypatch, raw):
    # 只提取到标准模式时透传；不再为未支持的相对时长建立专门对话。
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "closeOrderType": "TWAP"}])
    result = await _run(f"{ORDER} {raw}")
    assert result.get("error") is None
    assert len(sent) == 1
    row = sent[0]["closeOrderReqVO"]["closeOrderList"][0]
    assert row.get("closeOrderAlgoStartTime") is None
    assert row.get("closeOrderAlgoEndTime") is None
    assert sent[0]["rawContent"] == f"{ORDER} {raw}"
    assert not result.get("reply_text")


def test_relative_twap_candidate_has_no_special_split():
    candidates = close_candidates({"orderId": ORDER, "closeOrderType": "TWAP20分钟"})
    assert split_execution_fragments(candidates).model_dump() == candidates.model_dump()


@pytest.mark.parametrize("phrase,mode,ratio,expected", [
    ("最大跟量", None, None, True),
    ("尽快成交", None, None, True),
    ("拉满跟量", None, None, True),
    ("全跟量", None, None, True),
    ("尽快成交 POV9", "POV", "9", False),
    ("最大跟量 POV9", "POV", "9", True),
    ("最大跟量 TWAP", "TWAP", None, True),
    ("跟量", "跟量", None, False),
    ("跟量9%", "跟量", "9%", False),
])
async def test_fast_execution_is_an_intent_not_a_local_default(
    monkeypatch, phrase, mode, ratio, expected,
):
    assert "has_fast_execution_intent" in CloseOrderItem.model_fields
    sent = _isolate(monkeypatch, [{
        "orderId": ORDER, "closeOrderType": mode, "closeOrderPovRatio": ratio,
        "hasFastExecutionIntent": phrase,
    }])
    result = await _run(f"{ORDER} {phrase}")
    assert result.get("error") is None, result.get("error")
    assert len(sent) == 1
    row = sent[0]["closeOrderReqVO"]["closeOrderList"][0]
    assert row["hasFastExecutionIntent"] is expected
    assert row.get("closeOrderType") == ("POV" if mode == "跟量" else mode)
    assert row.get("closeOrderPovRatio") == (float(ratio.rstrip("%")) if ratio else None)
    record = result["field_records"]["close/place_close.orderList.0.hasFastExecutionIntent"]
    assert record.evidence == phrase and record.value is expected and record.locked


@pytest.mark.parametrize("raw", ["不要最大跟量", "如果可以就尽快成交", "尽快成交吗"])
async def test_fast_execution_must_be_affirmative(monkeypatch, raw):
    assert "has_fast_execution_intent" in CloseOrderItem.model_fields
    phrase = "最大跟量" if "最大跟量" in raw else "尽快成交"
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "hasFastExecutionIntent": phrase}])
    result = await _run(f"{ORDER} {raw}")
    assert result.get("error") is not None
    assert sent == []


async def test_fast_execution_cannot_leak_between_orders(monkeypatch):
    assert "has_fast_execution_intent" in CloseOrderItem.model_fields
    sent = _isolate(monkeypatch, [
        {"orderId": ORDER, "hasFastExecutionIntent": "最大跟量"},
        {"orderId": SECOND, "closeOrderType": "市价"},
    ])
    result = await _run(f"{ORDER} 最大跟量；{SECOND} 市价")
    assert result.get("error") is None
    first, second = sent[0]["closeOrderReqVO"]["closeOrderList"]
    assert first["hasFastExecutionIntent"] is True
    assert second.get("hasFastExecutionIntent") is None


async def test_explicit_maximum_in_same_order_takes_priority_over_ratio(monkeypatch):
    # 模型可能只提取一个加速词；本轮同一订单的“最大跟量”优先级仍必须保留。
    sent = _isolate(monkeypatch, [{
        "orderId": ORDER, "hasFastExecutionIntent": "尽快成交",
        "closeOrderType": "POV", "closeOrderPovRatio": "9",
    }])
    result = await _run(f"{ORDER} 最大跟量，尽快成交，POV9")
    assert result.get("error") is None
    row = sent[0]["closeOrderReqVO"]["closeOrderList"][0]
    assert row["hasFastExecutionIntent"] is True
    assert row["closeOrderPovRatio"] == 9


async def test_code_500_preserves_original_receipt(monkeypatch):
    sent = _isolate(monkeypatch, [{"orderId": ORDER, "closeOrderType": "限价"}],
                    response={"code": 500, "msg": "Java原始失败原因"})
    result = await _run(f"{ORDER} 限价")
    assert len(sent) == 1
    assert result["api_code"] == 500 and result["api_result"] == "Java原始失败原因"
    assert (await render({**result, "product_type": "option_close"}))["reply_text"] == "交易指令服务暂不可用"


def test_unknown_counterparty_keeps_dify_sentinel_filter():
    params, _ = normalize_holding_candidates(
        holding_candidates(keyCtptyIdList=["未匹配账户"]),
        {"raw": "查对手未匹配账户的持仓"},
        [{"ctptyId": 10049, "shortName": "临沂阿凡提"}],
    )
    assert params.key_ctpty_id_list == [99999999]
