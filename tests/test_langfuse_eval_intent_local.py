"""意图集本地确定性评分：不依赖 Langfuse / Java / GOATS，可在 CI 里给出退出码。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import langfuse
import pytest

from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input
from scripts.langfuse import langfuse_eval
from scripts.langfuse.langfuse_eval import _LocalItem, case_passed, code_evaluations


def _instrument_case() -> GoldenCase:
    return GoldenCase(
        id="intent-swap-instrument-1",
        category="intent/swap",
        turns=[
            TurnSpec(
                send_text="港股市价买一百万京东",
                at_bot=True,
                expected={
                    "product_type": "swap",
                    "intent": "place_order_request",
                    "instruments": [{"expression": ["京东"], "transaction_type": ["HK_STOCK"]}],
                },
            )
        ],
        expected={"product_type": "swap", "intent": "place_order_request"},
    )


def test_dataset_shape_helpers_live_in_harness() -> None:
    """上传脚本与本地评分共用同一份 categories 结构投影。"""
    case = GoldenCase(
        id="c",
        category="intent/option_close",
        turns=[
            TurnSpec(send_text="我想平仓", at_bot=True, expected={"product_type": "option_close", "intent": "close_order_query"}),
            TurnSpec(send_text="确认平仓", quote_previous=True, expected={"intent": "close_order_confirm"}, response_not_contains=["互换订单"]),
        ],
    )
    assert dataset_input(case) == {
        "send_text": "我想平仓",
        "at_bot": True,
        "sub_scenes": [{"send_text": "确认平仓", "at_bot": False, "quote_previous": True}],
    }
    assert dataset_expected(case) == {
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "sub_scenes": [{"expected": {"intent": "close_order_confirm"}, "response_not_contains": ["互换订单"]}],
    }


def test_local_item_carries_structured_expected_for_code_evaluators() -> None:
    item = _LocalItem(_instrument_case(), suite="intent")
    assert item.expected_structured == dataset_expected(_instrument_case())
    assert item.has_instruments is True
    assert _LocalItem(GoldenCase(id="x", category="intent/swap", turns=[TurnSpec(send_text="x")])).has_instruments is False


def test_code_evaluations_run_intent_and_instrument_match_locally() -> None:
    item = _LocalItem(_instrument_case(), suite="intent")
    output = {
        "turns": [
            {
                "product_type": "swap",
                "intent": "place_order_request",
                "place_params": {
                    "orderList": [{"placeOrderWindCode": "京东", "placeOrderTransactionType": "HK_STOCK"}]
                },
            }
        ]
    }
    evaluations = code_evaluations(item, output)
    assert [ev.name for ev in evaluations] == ["det_intent_match_pass", "det_instrument_match_pass"]
    assert [ev.value for ev in evaluations] == [1.0, 1.0]

    wrong = {"turns": [{"product_type": "swap", "intent": "confirm_order", "place_params": {"orderList": []}}]}
    evaluations = code_evaluations(item, wrong)
    assert [ev.value for ev in evaluations] == [0.0, 0.0]
    assert "intent 不符" in (evaluations[0].comment or "")

    plain = _LocalItem(
        GoldenCase(id="p", category="intent/swap", turns=[TurnSpec(send_text="x", expected={"product_type": "swap", "intent": "confirm_order"})]),
        suite="intent",
    )
    assert [ev.name for ev in code_evaluations(plain, wrong)] == ["det_intent_match_pass"]


def test_case_passed_semantics_per_suite() -> None:
    ok = SimpleNamespace(name="det_intent_match_pass", value=1.0)
    bad = SimpleNamespace(name="det_instrument_match_pass", value=0.0)
    assert case_passed("intent", [ok, ok]) is True
    assert case_passed("intent", [ok, bad]) is False
    assert case_passed("business", [SimpleNamespace(name="otc-option-judge", value=0.7)]) is True
    assert case_passed("business", [SimpleNamespace(name="otc-option-judge", value=0.5)]) is False


class _IntentGraph:
    """按输入文本返回固定路由结果；第二条用例故意答错意图。"""

    async def ainvoke(self, state: dict, config: dict) -> dict:
        text = state.get("raw_text", "")
        intent = "place_order_request" if "京东" in text else "query_order_status"
        return {
            **state,
            "product_type": "swap",
            "intent": intent,
            "reply_text": "ok",
            "api_code": 0,
            "error": None,
            "place_params": {"orderList": [{"placeOrderWindCode": "京东", "placeOrderTransactionType": "HK_STOCK"}]},
        }


class _NoLangfuse:
    def __init__(self) -> None:
        raise RuntimeError("langfuse disabled in test")


def _write_intent_fixture(path: Path) -> None:
    rows = [
        {
            "caseNo": "intent-swap-1",
            "name": "京东",
            "category": "intent/swap",
            "type": "positive",
            "send_text": "港股市价买一百万京东",
            "at_bot": True,
            "expected": {
                "product_type": "swap",
                "intent": "place_order_request",
                "instruments": [{"expression": ["京东"], "transaction_type": ["HK_STOCK"]}],
            },
            "sub_scenes": [],
        },
        {
            "caseNo": "intent-swap-2",
            "name": "确认",
            "category": "intent/swap",
            "type": "positive",
            "send_text": "确认下单",
            "at_bot": True,
            "expected": {"product_type": "swap", "intent": "confirm_order"},
            "sub_scenes": [],
        },
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@pytest.mark.asyncio
async def test_run_local_intent_suite_scores_without_langfuse_and_writes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = tmp_path / "swap.jsonl"
    _write_intent_fixture(fixture)
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: _IntentGraph())
    monkeypatch.setattr(langfuse_eval, "_TURN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(langfuse_eval, "_graph_callbacks", lambda: [])
    monkeypatch.setattr(langfuse, "Langfuse", _NoLangfuse)
    report = tmp_path / "intent-eval.json"

    summary = await langfuse_eval.run_local(
        [fixture], None, None, 1, None, False, False, suite="intent", report=report
    )

    assert summary["suite"] == "intent"
    assert (summary["total"], summary["passed"]) == (2, 1)
    assert summary["pass_rate"] == 0.5
    failed = [case for case in summary["cases"] if not case["passed"]]
    assert [case["id"] for case in failed] == ["intent-swap-2"]
    assert failed[0]["evaluations"][0]["name"] == "det_intent_match_pass"
    assert "期望 confirm_order，实际 query_order_status" in failed[0]["evaluations"][0]["comment"]

    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["pass_rate"] == 0.5
    assert [case["id"] for case in written["cases"]] == ["intent-swap-1", "intent-swap-2"]

    out = capsys.readouterr().out
    assert "通过率: 1/2" in out
    assert "det_intent_match_pass" in out


def test_main_fail_under_turns_pass_rate_into_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_run_local(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"suite": kwargs.get("suite"), "total": 2, "passed": 1, "pass_rate": 0.5, "cases": []}

    monkeypatch.setattr(langfuse_eval, "run_local", fake_run_local)
    fixture = tmp_path / "intent"
    fixture.mkdir()

    monkeypatch.setattr(sys, "argv", ["langfuse_eval.py", "--local", str(fixture), "--fail-under", "0.9"])
    assert langfuse_eval.main() == 1
    monkeypatch.setattr(sys, "argv", ["langfuse_eval.py", "--local", str(fixture), "--fail-under", "0.5"])
    assert langfuse_eval.main() == 0
    monkeypatch.setattr(sys, "argv", ["langfuse_eval.py", "--local", str(fixture)])
    assert langfuse_eval.main() == 0
