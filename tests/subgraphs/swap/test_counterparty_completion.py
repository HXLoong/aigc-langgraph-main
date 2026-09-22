"""旧尾部补全已迁移：提取节点保留模型原值，交给全新对手识别节点裁决。"""
from __future__ import annotations

from copy import deepcopy

import pytest

from app.subgraphs.swap import place_order
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from tests.subgraphs.swap.test_fresh_counterparty import fresh_state, patch_recognition
from tests.subgraphs.swap.test_fresh_counterparty_graph import graph_boundaries


@pytest.mark.parametrize(("raw", "shortname", "accounts"), [
    ("NVDA卖出100股，TSM卖出200股 测试账户。", "测试账户", ["1"]),
    ("测试账户 NVDA/TSM", "测试账户", ["1"]),
    ("NVDA/TSM 测试账户", "测试账户", ["1", "2"]),
    ("NVDA/TSM 测试账户", "测试账户", [None, None]),
    ("NVDA/TSM 交易对手：1453。", "1453", ["1"]),
    ("NVDA/TSM 账号 1453", "1453", ["1"]),
])
@pytest.mark.parametrize("names", [[None], [None, None], ["已有账户", None]])
async def test_extraction_leaves_all_counterparty_decisions_to_downstream_node(
    monkeypatch: pytest.MonkeyPatch, raw: str, shortname: str,
    accounts: list[str | None], names: list[str | None],
) -> None:
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(placeOrderWindCode="NVDA", placeOrderShortname=name) for name in names
    ])
    original = deepcopy(params.model_dump())
    state, _requests = graph_boundaries(monkeypatch, params)
    raw += " " + " ".join(name for name in names if name)
    state["raw_text"] = raw
    state["swap_counterparties"] = [
        {"ctptyId": account, "shortName": shortname} for account in accounts
    ]

    output = await place_order.swap_place_order(state)

    assert not output.get("error"), output.get("error")
    assert [o["placeOrderShortname"] for o in output["place_params"]["orderList"]] == names
    assert params.model_dump() == original
    assert state["raw_text"] == raw
    assert "counterparty_completion" not in next(e for e in output["trace"] if e.node == "swap_place_order").llm_output


@pytest.mark.parametrize("original_name", [None, "1453"])
async def test_numeric_name_exclusion_is_model_recall_rule_and_preserves_extracted_value(
    monkeypatch: pytest.MonkeyPatch, original_name: str | None,
) -> None:
    """旧规则在有“对手/账号”标签时补数字名；现行提示词一律跳过纯数字候选。

    模拟符合提示词约定的无信号输出，代码保留提取值；不宣称此测试验证真实模型识别率。
    """
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty

    state = fresh_state([None, original_name])
    state["raw_text"] = "NVDA/TSM 交易对手：1453。"
    state["swap_counterparties"] = [{"shortName": "1453"}]
    patch_recognition(monkeypatch, {"hasSignal": False, "matches": []})

    output = await swap_recognize_fresh_counterparty(state)

    assert output["place_params"] == state["place_params"]
    assert output["trace"][0].llm_output["reason"] == "no_signal"
