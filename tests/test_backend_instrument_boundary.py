"""Instrument boundary: extract instrument expressions; Java resolves securities."""
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_inquiry as inquiry
from app.subgraphs.swap import apply_picks, multimodal, place_order, select_ticker
from app.tools.ticker_client import TickerClientHttpx


def field(value, *, origin="raw", reference=None):
    return {"value": value, "evidence": value, "confidence": .9,
            "origin": origin, "reference": reference}


def model(monkeypatch, module, factory, payload):
    fake = MagicMock()
    fake.with_structured_output.return_value.ainvoke = AsyncMock(return_value=payload)
    monkeypatch.setattr(module, factory, lambda: fake)
    return fake


_LOCAL_RESOLUTION_RX = re.compile(r"resolve_ticker|TickerClient|ticker_client|from_goats=True")


def test_business_graphs_do_not_import_local_instrument_resolution() -> None:
    """标的识别委托后端（CLAUDE.md 原则 7）：业务子图与节点不得再引用本地证券解析。

    旧守卫靠 monkeypatch 一个已不存在的 `resolve_ticker_full`，恒真无效；这里直接断言导入面。
    """
    roots = (pathlib.Path("app/subgraphs"), pathlib.Path("app/nodes"), pathlib.Path("app/graph"))
    offenders = sorted(
        str(path) for root in roots for path in root.rglob("*.py")
        if _LOCAL_RESOLUTION_RX.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], offenders


@pytest.mark.parametrize("instrument", ["沪铜主力", "9月沪铜", "宁德时代", "2333长城汽车", "cu2609.shf", "00700"])
async def test_swap_preserves_instrument_at_submit(monkeypatch, instrument):
    model(monkeypatch, place_order, "get_qwen_complex", {"orderList": [{
        "placeOrderWindCode": field(instrument), "placeOrderQuantity": field("8万股"),
        "placeOrderOrderDirection": field("买入"),
    }]})
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "后端处理结果"})
    monkeypatch.setattr(place_order, "call_swap_backend", backend)
    state = {"raw_text": f"{instrument} 买入 8万股"}
    extracted = await place_order.swap_place_order(state)
    assert not extracted.get("error")
    result = await place_order.swap_place_order_submit({**state, **extracted})
    sent = backend.await_args.kwargs["order_list"][0]
    assert sent["placeOrderWindCode"] == instrument
    assert sent["placeOrderQuantity"] == 80000
    assert result["api_result"] == "后端处理结果"


@pytest.mark.parametrize("instrument", ["宁德时代", "2333长城汽车", "000000.SZ"])
async def test_inquiry_reaches_backend_even_for_unknown_instrument(monkeypatch, instrument):
    model(monkeypatch, inquiry, "get_qwen_thinking", {"orderList": [{
        "stockCode": field(instrument), "tenor": field("1个月"),
        "optionType": field("欧式看涨"), "strikePercentage": field("80%"),
    }]})
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "后端：标的待核实"})
    monkeypatch.setattr(inquiry, "call_option_backend", backend)
    result = await inquiry.option_extract_inquiry({"raw_text": f"{instrument} 欧式看涨 1个月 80%"})
    assert not result.get("error")
    assert backend.await_args.kwargs["order_list"][0]["stockCode"] == instrument
    assert result["api_result"] == "后端：标的待核实"


async def test_attachment_expression_needs_evidence_but_no_local_security_lookup(monkeypatch):
    text = "新证券 买入 100股"
    model(monkeypatch, multimodal, "get_qwen_vl", {"text": text})
    model(monkeypatch, multimodal, "get_qwen_structured", {"orderList": [{
        "placeOrderWindCode": field("新证券", origin="attachment", reference="file:0:image"),
        "placeOrderQuantity": field("100股", origin="attachment", reference="file:0:image"),
    }]})
    result = await multimodal.swap_image_order({"input_files": [{"type": "image", "url": "https://example.test/image"}]})
    assert not result.get("error")
    assert result["place_params"]["orderList"][0]["placeOrderWindCode"] == "新证券"
    record = result["field_records"]["swap/place_order.orderList.0.placeOrderWindCode"]
    assert record.source == "user" and record.origin == "attachment:file:0:image"


@pytest.mark.parametrize("raw,expected,origin", [("选标的1", "AAPL.O", "quote"), ("换成腾讯控股", "腾讯控股", "raw")])
async def test_selection_is_quote_lookup_or_raw_expression(monkeypatch, raw, expected, origin):
    oid = "H-20260918-0000000001"
    state = {"raw_text": raw, "quote_content": f"订单{oid} 候选标的：1.AAPL.O 苹果",
             "place_params": {"orderList": [{"orderId": oid}]},
             "quote_ticker_candidates": [{"orderId": oid, "candidates": [{"seq": 1, "code": "AAPL.O", "name": "苹果"}]}]}
    model(monkeypatch, select_ticker, "get_qwen_complex", {"picks": [{
        "orderId": oid, "idx": 0, "directRef": expected, "evidence": raw, "confidence": .9,
    }]})
    selected = await select_ticker.swap_select_ticker(state)
    assert not selected.get("error")
    result = await apply_picks.swap_apply_picks({**state, **selected})
    assert not result.get("error")
    assert result["place_params"]["orderList"][0]["placeOrderWindCode"] == expected
    record = result["field_records"]["swap/place_order.orderList.0.placeOrderWindCode"]
    assert record.source != "goats" and record.origin == origin


@pytest.mark.parametrize("raw", ["选B", "换成市价", "换成POV", "选100股"])
def test_parameter_or_account_choice_is_not_a_new_security(raw):
    from app.subgraphs.swap.selection_rules import ticker_choice

    state = {"raw_text": raw, "place_params": {"orderList": [{"orderId": "H-1"}]},
             "quote_ticker_candidates": [{"orderId": "H-1", "candidates": [{"seq": 1, "code": "AAPL.O", "name": "苹果"}]}],
             "swap_counterparties": [{"sort": "B", "shortName": "账户乙"}]}
    result = ticker_choice(state)
    assert result is None or not result.picks


def test_ticker_client_exposes_no_instrument_lookup() -> None:
    """ADR 0025：标的识别归 Java，TickerClient 只保留授权交易对手列表查询。"""
    for name in ("search_securities_instrument", "get_inference_prompt"):
        assert not hasattr(TickerClientHttpx, name), name
