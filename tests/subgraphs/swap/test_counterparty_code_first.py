"""Authorized literal names can be resolved without model interpretation."""
from unittest.mock import MagicMock

from app.subgraphs.swap import fresh_counterparty as module


async def test_exact_authorized_name_repairs_overwide_candidate_without_llm(monkeypatch):
    llm = MagicMock(side_effect=AssertionError("exact name must skip LLM"))
    monkeypatch.setattr(module, "get_qwen_complex", llm)
    name = "测试账户甲"
    result = await module.swap_recognize_fresh_counterparty({
        "raw_text": "买入 COIN 6526股 COMPO 测试账户甲",
        "swap_counterparties": [{"shortName": name, "ctptyId": "1"}],
        "place_params": {"orderList": [{"placeOrderShortname": "COMPO 测试账户甲"}]},
    })
    assert not result.get("error")
    assert result["place_params"]["orderList"][0]["placeOrderShortname"] == name
    llm.assert_not_called()
    record = result["field_records"]["swap/place_order.orderList.0.placeOrderShortname"]
    assert record.source == "goats" and record.locked and record.value == name


async def test_exact_name_does_not_override_a_different_explicit_account(monkeypatch):
    monkeypatch.setattr(module, "get_qwen_complex", MagicMock(side_effect=AssertionError("no LLM")))
    result = await module.swap_recognize_fresh_counterparty({
        "raw_text": "测试账户甲买入100股", "swap_counterparties": [{"shortName": "测试账户甲"}],
        "place_params": {"orderList": [{"placeOrderShortname": "独立账户乙"}]},
    })
    assert not result.get("error")
    assert result["place_params"]["orderList"][0]["placeOrderShortname"] == "独立账户乙"
