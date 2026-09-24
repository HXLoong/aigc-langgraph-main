"""意图集本地确定性评分：不依赖 Langfuse / Java / GOATS，可在 CI 里给出退出码。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import langfuse
import pytest

from harness import intent_runner
from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input, load_golden
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
    """上传脚本与本地评分共用同一份 biz 结构投影。"""
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


def _main_graph_forbidden(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("intent suite must not build the main graph (it needs backends)")


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
    monkeypatch.setattr(intent_runner, "build_intent_graph", lambda **_: _IntentGraph())
    monkeypatch.setattr(langfuse_eval, "build_main_graph", _main_graph_forbidden)
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


class _RecordingGraph:
    """记录每轮收到的 state；第 1 轮故意报错，验证逐轮独立、不早停。"""

    def __init__(self) -> None:
        self.states: list[dict] = []

    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        self.states.append(dict(state))
        if len(self.states) == 1:
            return {**state, "product_type": "unknown", "intent": "", "error": {"node": "intent_route", "message": "boom"}}
        return {**state, "product_type": "option_close", "intent": "close_order_confirm", "error": None}


@pytest.mark.asyncio
async def test_intent_pipeline_runs_every_turn_with_frozen_context(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingGraph()
    monkeypatch.setattr(intent_runner, "build_intent_graph", lambda **_: recorder)
    monkeypatch.setattr(langfuse_eval, "build_main_graph", _main_graph_forbidden)
    monkeypatch.setattr(langfuse_eval, "_graph_callbacks", lambda: [])
    case = GoldenCase(
        id="intent-option_close-x",
        category="intent/option_close",
        turns=[
            TurnSpec(send_text="我想平仓", at_bot=True, expected={"product_type": "option_close", "intent": "close_order_query"}),
            TurnSpec(
                send_text="确认平仓",
                quote_content="以下平仓申请，请核对详情后确认：单号：CO-20260506-DEAF117C",
                history=[{"role": "user", "content": "我想平仓"}],
                prev_product_type="option_close",
                expected={"product_type": "option_close", "intent": "close_order_confirm"},
            ),
        ],
    )
    output = await langfuse_eval.run_langgraph_pipeline(item=_LocalItem(case, suite="intent"), suite="intent")

    assert len(output["turns"]) == 2, "intent suite evaluates every turn; no early stop"
    assert "failure" not in output
    assert output["turns"][0]["error"] == {"node": "intent_route", "type": None, "message": "boom"}
    second = recorder.states[1]
    assert second["quote_content"] == "以下平仓申请，请核对详情后确认：单号：CO-20260506-DEAF117C"
    assert second["product_type"] == "option_close"
    assert [(m.role, m.content) for m in second["history_messages"]] == [("user", "我想平仓")]
    assert recorder.states[0].get("quote_content") in (None, "")
    assert output["turns"][1]["intent"] == "close_order_confirm"
    assert output["turns"][1]["quote_passed"].startswith("以下平仓申请")


def test_frozen_context_round_trips_through_loader_and_dataset_projection(tmp_path: Path) -> None:
    fixture = tmp_path / "option_close.jsonl"
    row = {
        "caseNo": "intent-option_close-1",
        "category": "intent/option_close",
        "type": "positive",
        "send_text": "我想平仓",
        "at_bot": True,
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "sub_scenes": [
            {
                "send_text": "确认平仓",
                "quote_content": "单号：CO-20260506-DEAF117C 请引用本消息回复【确认平仓】",
                "history": [{"role": "assistant", "content": "以下是您的期权持仓："}],
                "prev_product_type": "option_close",
                "expected": {"product_type": "option_close", "intent": "close_order_confirm"},
            }
        ],
    }
    fixture.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    (case,) = load_golden([fixture])
    turn = case.turns[1]
    assert turn.quote_content.startswith("单号：CO-20260506-DEAF117C")
    assert turn.history == [{"role": "assistant", "content": "以下是您的期权持仓："}]
    assert turn.prev_product_type == "option_close"
    assert case.turns[0].quote_content == "" and case.turns[0].history == []

    projected = dataset_input(case)["sub_scenes"][0]
    assert projected["quote_content"] == turn.quote_content
    assert projected["history"] == turn.history
    assert projected["prev_product_type"] == "option_close"
    assert not {"quote_content", "history", "prev_product_type"} & set(dataset_input(case)), "empty context stays out"

    local = _LocalItem(case, suite="intent").input["turns"][1]
    assert (local["quote_content"], local["history"], local["prev_product_type"]) == (
        turn.quote_content, turn.history, "option_close"
    )


def test_labeled_rejection_requires_rejection_score_in_addition_to_intent():
    case = GoldenCase(id='reject', category='intent/swap', type='negative', turns=[
        TurnSpec(send_text='甲证券已买100股', expected={
            'product_type': 'swap', 'intent': 'place_order_request', 'rejection': 'ambiguous_action',
        }),
    ])
    item = _LocalItem(case, suite='intent')
    output = {'turns': [{'product_type': 'swap', 'intent': 'place_order_request',
                        'error': None, 'reply_text': '错误地接受委托'}]}
    evaluations = code_evaluations(item, output)
    assert [e.name for e in evaluations] == ['det_intent_match_pass', 'det_rejection_match_pass']
    assert not case_passed('intent', evaluations)


def test_quality_gate_does_not_hide_unsafe_rejection_failure_in_high_total():
    summary = {'suite': 'intent', 'pass_rate': .99, 'acceptance_buckets': {
        'executable': {'total': 100, 'passed': 99, 'pass_rate': .99},
        'expected_rejection': {'total': 27, 'passed': 26, 'pass_rate': 26/27},
    }}
    assert not langfuse_eval.passes_quality_gate(summary, .95)
    summary['acceptance_buckets']['expected_rejection'].update(passed=27, pass_rate=1.0)
    assert langfuse_eval.passes_quality_gate(summary, .95)
    summary['acceptance_buckets']['executable']['pass_rate'] = .94
    assert not langfuse_eval.passes_quality_gate(summary, .95)


class _ReplayGraph:
    async def ainvoke(self, state: dict, config: dict) -> dict:
        return {**state, "product_type": "option_close", "intent": "close_order_query",
                "reply_text": "以下是您的期权持仓：", "api_code": 0, "error": None}


@pytest.mark.asyncio
async def test_intent_cases_that_replay_previous_reply_keep_main_graph_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两种模式并存：未冻结、需要引用上一轮回复的用例继续走主图 + mock 回放。"""
    def _intent_chain_forbidden(**_: object) -> None:
        raise AssertionError("replay case must not run on the frozen intent chain")

    monkeypatch.setattr(intent_runner, "build_intent_graph", _intent_chain_forbidden)
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: _ReplayGraph())
    monkeypatch.setattr(langfuse_eval, "TickerClientHttpx", lambda: SimpleNamespace(
        list_counterparty=AsyncMock(return_value=[]),
    ))
    monkeypatch.setattr(langfuse_eval, "_TURN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(langfuse_eval, "_graph_callbacks", lambda: [])
    case = GoldenCase(
        id="intent-option_close-replay",
        category="intent/option_close",
        turns=[
            TurnSpec(send_text="查可平持仓", at_bot=True, expected={"product_type": "option_close", "intent": "close_order_query"}),
            TurnSpec(send_text="我想平掉 {{previous_holding_contract_id:1}}", quote_previous=True,
                     expected={"product_type": "option_close", "intent": "close_order_request"}),
        ],
    )
    output = await langfuse_eval.run_langgraph_pipeline(item=_LocalItem(case, suite="intent"), suite="intent")
    assert output["mode"] == "main_graph"
    assert output["turns"][1]["quote_passed"].startswith("以下是您的期权持仓")


@pytest.mark.asyncio
async def test_frozen_intent_cases_report_intent_chain_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_runner, "build_intent_graph", lambda **_: _IntentGraph())
    monkeypatch.setattr(langfuse_eval, "build_main_graph", _main_graph_forbidden)
    monkeypatch.setattr(langfuse_eval, "_graph_callbacks", lambda: [])
    case = GoldenCase(id="intent-swap-f", category="intent/swap", turns=[
        TurnSpec(send_text="确认下单", at_bot=True, expected={"product_type": "swap", "intent": "confirm_order"}),
    ])
    output = await langfuse_eval.run_langgraph_pipeline(item=_LocalItem(case, suite="intent"), suite="intent")
    assert output["mode"] == "intent_chain"


@pytest.mark.asyncio
async def test_rejection_cases_keep_main_graph_for_user_visible_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝验收要检查面向用户的拒绝回复与“未提交后端”，只有主图（render / fallback）能给出。"""
    def _intent_chain_forbidden(**_: object) -> None:
        raise AssertionError("rejection case must run the main graph")

    monkeypatch.setattr(intent_runner, "build_intent_graph", _intent_chain_forbidden)
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: _ReplayGraph())
    monkeypatch.setattr(langfuse_eval, "TickerClientHttpx", lambda: SimpleNamespace(
        list_counterparty=AsyncMock(return_value=[]),
    ))
    monkeypatch.setattr(langfuse_eval, "_graph_callbacks", lambda: [])
    case = GoldenCase(id="intent-swap-reject", category="intent/swap", type="negative", turns=[
        TurnSpec(send_text="卖出 -100 股", at_bot=True, expected={
            "product_type": "swap", "intent": "place_order_request", "rejection": "non_positive_quantity",
        }),
    ])
    output = await langfuse_eval.run_langgraph_pipeline(item=_LocalItem(case, suite="intent"), suite="intent")
    assert output["mode"] == "main_graph"
    remote = SimpleNamespace(
        input={"send_text": "卖出 -100 股", "at_bot": True, "sub_scenes": []},
        expected_output={"expected": {"rejection": "non_positive_quantity"}, "sub_scenes": []},
    )
    assert (await langfuse_eval.run_langgraph_pipeline(item=remote, suite="intent"))["mode"] == "main_graph"
