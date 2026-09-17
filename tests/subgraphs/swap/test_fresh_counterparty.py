"""全新交易对手节点：模型候选经 Dify 聚合规则校验后写回订单。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import AgentState


def patch_recognition(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> AsyncMock:
    from app.subgraphs.swap import fresh_counterparty
    from app.subgraphs.swap.models import SwapFreshCounterpartyOutput

    async def respond(_messages: Any) -> SwapFreshCounterpartyOutput:
        return SwapFreshCounterpartyOutput.model_validate(payload)

    invoke = AsyncMock(side_effect=respond)
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(fresh_counterparty, "get_qwen_complex", lambda: model)
    return invoke


def fresh_state(names: list[str | None] | None = None) -> AgentState:
    return {
        "raw_text": "平仓价值精选全部持仓",
        "swap_counterparties": [
            {"sort": "A", "shortName": "聚鸣价值精选", "ctptyId": "1", "longName": "后台全称"},
        ],
        "place_params": {
            "orderList": [
                {
                    "placeOrderShortname": name,
                    "placeOrderWindCode": "NVDA.O",
                    "placeOrderQuantity": 1453,
                    "placeOrderPrice": "883.9758",
                    "placeOrderDirection": "SELL",
                    "placeOrderAlgorithmType": "TWAP",
                    "placeOrderCloseIntent": True,
                    "placeOrderEntrustRatio": 100,
                    "extension": {"preserve": [1, 2]},
                }
                for name in (names if names is not None else [None])
            ],
        },
    }


@pytest.mark.parametrize("case", [
    json.loads(line)
    for line in (
        Path(__file__).resolve().parents[2]
        / "fixtures/golden_swap_fresh_counterparty.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    if line.strip()
], ids=lambda case: case["id"])
async def test_unique_name_completes_orders_without_changing_input_or_other_fields(
    monkeypatch: pytest.MonkeyPatch, case: dict[str, Any],
) -> None:
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty

    names = case["initial_counterparty_names"]
    state = fresh_state(names)
    state["raw_text"] = case["raw_content"]
    original = deepcopy(state)
    recall = case["llm_response"]
    patch_recognition(monkeypatch, recall)

    output = await swap_recognize_fresh_counterparty(state)

    assert not output.get("error"), output.get("error")
    expected = deepcopy(original["place_params"])
    for order, golden_order in zip(
        expected["orderList"], case["expected"]["place_params"]["orderList"], strict=True,
    ):
        order["placeOrderShortname"] = golden_order["placeOrderShortname"]
    assert output["place_params"] == expected
    assert state == original
    assert set(output) == {"place_params", "trace"}
    trace = output["trace"][0]
    assert trace.node == "swap_recognize_fresh_counterparty"
    assert trace.llm_output["recall"] == recall
    assert trace.llm_output["adopted"] is True
    assert trace.llm_output["affected_orders"] == [i for i, name in enumerate(names) if name is None]


@pytest.mark.parametrize(("recall", "names", "reason"), [
    ({"hasSignal": False, "matches": []}, [None], "no_signal"),
    ({"hasSignal": True, "matches": []}, [None], "no_matches"),
    ({"hasSignal": True, "matches": [{"shortName": "候选外账户", "evidence": "价值精选"}]},
     [None], "name_outside_candidates"),
    ({"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选", "evidence": "原文没有"}]},
     [None], "invalid_evidence"),
    ({"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选", "evidence": "   "}]},
     [None], "invalid_evidence"),
    ({"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选"},
        {"shortName": "另一价值精选", "evidence": "价值精选"},
    ]}, [None, None], "ambiguous_names"),
    ({"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选"},
        {"shortName": "候选外账户", "evidence": "价值精选"},
    ]}, [None], "name_outside_candidates"),
    ({"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选"},
        {"shortName": "另一价值精选", "evidence": "原文没有"},
    ]}, [None], "invalid_evidence"),
    ({"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选", "evidence": "价值精选"}]},
     [None, "另一价值精选"], "existing_counterparty_conflict"),
    ({"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选", "evidence": "价值精选"}]},
     ["聚鸣价值精选", "另一价值精选", None], "existing_counterparty_conflict"),
    ({"hasSignal": False, "matches": [{"shortName": "聚鸣价值精选", "evidence": "价值精选"}]},
     [None], "no_signal"),
])
async def test_unusable_recall_preserves_entire_batch_and_explains_why(
    monkeypatch: pytest.MonkeyPatch, recall: dict[str, Any], names: list[str | None], reason: str,
) -> None:
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty

    state = fresh_state(names)
    state["swap_counterparties"].append({"sort": "B", "shortName": "另一价值精选"})
    original = deepcopy(state)
    patch_recognition(monkeypatch, recall)
    output = await swap_recognize_fresh_counterparty(state)

    assert output["place_params"] == original["place_params"]
    assert state == original
    trace = output["trace"][0].llm_output
    assert trace["recall"] == recall
    assert trace["adopted"] is False
    assert trace["reason"] == reason
    assert trace["affected_orders"] == []


@pytest.mark.parametrize("accounts", [["1", "1"], ["1", "2"], [None, None]])
async def test_dify_deduplicates_names_regardless_of_backend_account_ids(
    monkeypatch: pytest.MonkeyPatch, accounts: list[str | None],
) -> None:
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty

    state = fresh_state([None, "  聚鸣价值精选  "])
    state["swap_counterparties"] = [
        {"ctptyId": account, "shortName": "聚鸣价值精选"} for account in accounts
    ]
    patch_recognition(monkeypatch, {"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选"},
        {"shortName": " 聚鸣价值精选 ", "evidence": " 价值精选 "},
    ]})
    output = await swap_recognize_fresh_counterparty(state)

    assert [o["placeOrderShortname"] for o in output["place_params"]["orderList"]] == [
        "聚鸣价值精选", "聚鸣价值精选",
    ]
    assert output["trace"][0].llm_output["adopted"] is True


@pytest.mark.parametrize("payload", [
    {}, {"matches": []}, {"hasSignal": False}, {"hasSignal": None, "matches": []},
    {"hasSignal": "true", "matches": []}, {"hasSignal": True, "matches": None},
    {"hasSignal": True, "matches": [{}]},
    {"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选"}]},
    {"hasSignal": True, "matches": [{"evidence": "价值精选"}]},
    {"hasSignal": True, "matches": [{"shortName": None, "evidence": "价值精选"}]},
    {"hasSignal": True, "matches": [{"shortName": "聚鸣价值精选", "evidence": 1}]},
    {"hasSignal": False, "matches": [], "unexpected": True},
    {"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选", "unexpected": True},
    ]},
])
async def test_invalid_structured_output_enters_safe_node_error(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any],
) -> None:
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty

    patch_recognition(monkeypatch, payload)
    state = fresh_state()
    original = deepcopy(state)
    output = await swap_recognize_fresh_counterparty(state)

    assert output["error"].node == "swap_recognize_fresh_counterparty"
    assert output["error"].type == "ValidationError"
    assert "place_params" not in output
    assert state == original


async def test_model_receives_md_system_and_raw_text_plus_candidate_json_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0024 D1：git `.md` 是唯一真源——模型收到的 system 就是 fresh_counterparty.md 的
    system 段，user 只含原文 + 候选对手 JSON（{{raw_content}} / {{shortname_list}} 经 render_user 渲染），
    不夹带历史、引用或其它上下文；输出契约由 Pydantic 模型定义（必填 hasSignal / matches，禁止多余键）。"""
    from app.prompts import load_prompt
    from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty
    from app.subgraphs.swap.models import SwapFreshCounterpartyOutput

    state = fresh_state()
    state["raw_text"] = "NVDA 1453股 883.9758限价 聚鸣价值精选"
    invoke = patch_recognition(monkeypatch, {"hasSignal": False, "matches": []})
    output = await swap_recognize_fresh_counterparty(state)
    assert not output.get("error")

    prompt = load_prompt("swap", "fresh_counterparty")
    assert "{{raw_content}}" in prompt.user_template and "{{shortname_list}}" in prompt.user_template
    expected_user = (
        "raw_content：NVDA 1453股 883.9758限价 聚鸣价值精选\nshortname_list："
        + json.dumps([{"sort": "A", "shortName": "聚鸣价值精选"}], ensure_ascii=False)
    )
    assert invoke.await_args.args[0] == [("system", prompt.system), ("user", expected_user)]

    schema = SwapFreshCounterpartyOutput.model_json_schema()
    assert schema["required"] == ["hasSignal", "matches"]
    assert schema["additionalProperties"] is False
    match_schema = schema["$defs"]["SwapFreshCounterpartyMatch"]
    assert match_schema["required"] == ["shortName", "evidence"]
    assert match_schema["additionalProperties"] is False


@pytest.mark.parametrize("missing", ["candidates", "orders", "place_params"])
async def test_empty_candidates_or_orders_skip_model_and_keep_params(
    monkeypatch: pytest.MonkeyPatch, missing: str,
) -> None:
    from app.subgraphs.swap import fresh_counterparty

    state = fresh_state()
    if missing == "candidates":
        state["swap_counterparties"] = []
    elif missing == "orders":
        state["place_params"]["orderList"] = []
    else:
        state.pop("place_params")
    model = MagicMock(side_effect=AssertionError("empty inputs must skip recognition"))
    monkeypatch.setattr(fresh_counterparty, "get_qwen_complex", model)
    output = await fresh_counterparty.swap_recognize_fresh_counterparty(state)

    assert not output.get("error"), output.get("error")
    assert output["place_params"] == state.get("place_params", {"orderList": []})
    model.assert_not_called()
    trace = output["trace"][0].llm_output
    assert trace["recall"] is None
    assert trace["adopted"] is False
    assert trace["reason"] == ("no_candidates" if missing == "candidates" else "no_orders")
