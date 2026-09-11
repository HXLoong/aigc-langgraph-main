"""新文本多笔订单的尾部对手补齐，通过真实提取节点验证。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import AgentState
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.ticker import resolver


async def extract(
    monkeypatch: pytest.MonkeyPatch,
    raw_text: str,
    names: list[str | None],
    candidates: list[dict[str, Any]],
    **state_overrides: Any,
) -> dict[str, Any]:
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(placeOrderWindCode=code, placeOrderShortname=name)
        for code, name in zip(["NVDA", "TSM"], names, strict=False)
    ])
    if state_overrides.pop("existing_order", False):
        params.order_list[0].order_id = "H-20260911-1234567890"
    original = params.model_dump()
    llm = MagicMock()
    invoke = AsyncMock(return_value=params)
    llm.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(po_module, "get_qwen_complex", lambda: llm)
    for name in ("infer_code_batch", "split_ticker_keywords", "judge_ticker_type"):
        monkeypatch.setattr(resolver, name, AsyncMock(return_value={}))
    state: AgentState = {
        "raw_text": raw_text, "swap_counterparties": candidates, **state_overrides,
    }
    output = await po_module.swap_place_order(state)
    assert not output.get("error"), output.get("error")
    assert state["raw_text"] == raw_text
    assert params.model_dump() == original
    invoke.assert_awaited_once()
    return output


@pytest.mark.parametrize("names", [[None, "测试账户"], [None, None]])
async def test_fill_missing_counterparties_from_unique_trailing_shortname(
    monkeypatch: pytest.MonkeyPatch, names: list[str | None],
) -> None:
    output = await extract(
        monkeypatch, "NVDA卖出100股，TSM卖出200股 测试账户。 \n", names,
        [{"ctptyId": "1", "shortName": "测试账户"}],
    )
    assert [o["placeOrderShortname"] for o in output["place_params"]["orderList"]] == [
        "测试账户", "测试账户",
    ]
    assert [entry["result"] for entry in output["trace"][0].llm_output["counterparty_completion"]] == [
        "filled", "filled" if names[1] is None else "preserved",
    ]


@pytest.mark.parametrize(("raw", "names", "candidates", "overrides", "expected", "reason"), [
    ("NVDA 甲账户，TSM 乙账户", ["甲账户", "乙账户"],
     [{"shortName": "甲账户"}, {"shortName": "乙账户"}], {},
     ["甲账户", "乙账户"], "existing_value"),
    ("NVDA 甲账户，TSM 乙账户", [None, None],
     [{"shortName": "甲账户"}, {"shortName": "乙账户"}], {},
     [None, None], "multiple_counterparties"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"ctptyId": "1", "shortName": "测试账户"},
      {"ctptyId": "2", "shortName": "测试账户"}], {},
     [None, None], "ambiguous_accounts"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"ctptyId": "1", "shortName": "测试账户"},
      {"ctptyId": "1", "shortName": "测试账户"}], {},
     ["测试账户", "测试账户"], "unique_trailing_shortname"),
    ("NVDA/TSM 甲 测试账户", [None, None],
     [{"shortName": "测试账户"}, {"shortName": "甲 测试账户"}], {},
     ["甲 测试账户", "甲 测试账户"], "unique_trailing_shortname"),
    ("NVDA/TSM 测试账户（专用）！\n", [None, None],
     [{"shortName": "测试账户"}, {"shortName": "测试账户（专用）"}], {},
     ["测试账户（专用）", "测试账户（专用）"], "unique_trailing_shortname"),
    ("NVDA/TSM 测试账户（其他）", [None, None],
     [{"shortName": "测试账户（专用）"}], {}, [None, None], "no_trailing_shortname"),
    ("NVDA/TSM 非测试账户", [None, None],
     [{"shortName": "测试账户"}], {}, [None, None], "no_trailing_shortname"),
    ("NVDA/TSM 测试账户继续", [None, None],
     [{"shortName": "测试账户"}], {}, [None, None], "no_trailing_shortname"),
    ("测试账户 NVDA/TSM", [None, None],
     [{"shortName": "测试账户"}], {}, [None, None], "no_trailing_shortname"),
    ("NVDA/TSM 1453", [None, None],
     [{"shortName": "1453"}], {}, [None, None], "no_trailing_shortname"),
    ("NVDA卖出100股TSM卖出200股交易对手：1453。", [None, None],
     [{"shortName": "1453"}], {}, ["1453", "1453"], "unique_trailing_shortname"),
    ("NVDA/TSM 对手1453", [None, None],
     [{"shortName": "1453"}], {}, ["1453", "1453"], "unique_trailing_shortname"),
    ("NVDA/TSM 账号 1453", [None, None],
     [{"shortName": "1453"}], {}, ["1453", "1453"], "unique_trailing_shortname"),
    ("NVDA/TSM 股数1453", [None, None],
     [{"shortName": "1453"}], {}, [None, None], "no_trailing_shortname"),
    ("NVDA/TSM 测试账户", ["已有账户", "  "],
     [{"shortName": "测试账户"}], {}, ["已有账户", "测试账户"], "existing_value"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}], {"quote_content": "引用补参"},
     [None, None], "quoted_input"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}], {"quote_content": " Null "},
     ["测试账户", "测试账户"], "unique_trailing_shortname"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}], {"existing_order": True},
     [None, None], "existing_order"),
    ("H-20260911-1234567890 NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}], {}, [None, None], "existing_order"),
    ("NVDA 测试账户", [None], [{"shortName": "测试账户"}], {},
     [None], "not_multiple_orders"),
    ("NVDA/TSM 测试账户", [None, None], [], {}, [None, None], "no_trailing_shortname"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}], {"swap_input_mode": "image"},
     [None, None], "not_text_input"),
    ("NVDA/TSM 测试账户", [None, None],
     [{"shortName": "测试账户"}, {"shortName": "测试账户"}], {},
     [None, None], "ambiguous_accounts"),
])
async def test_counterparty_completion_guards(
    monkeypatch, raw, names, candidates, overrides, expected, reason,
) -> None:
    output = await extract(monkeypatch, raw, names, candidates, **overrides)
    assert [o["placeOrderShortname"] for o in output["place_params"]["orderList"]] == expected
    entries = output["trace"][0].llm_output["counterparty_completion"]
    assert len(entries) == len(names)
    assert entries[0]["reason"] == reason
