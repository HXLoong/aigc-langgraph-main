"""Prompt wire contracts: one copy per source and raw extraction semantics."""
import importlib
import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

MODULES = ["app.nodes.intent_route", "app.subgraphs.swap.intent", "app.subgraphs.option.intent",
           "app.subgraphs.close.intent", "app.subgraphs.close.place_close"]


@pytest.mark.parametrize("module_name", MODULES)
def test_sources_are_sent_once_with_roles(module_name):
    spec = importlib.import_module(module_name).SPEC
    state = {"raw_text": "CURRENT_UNIQUE", "quote_content": "QUOTE_UNIQUE",
             "bot_name": "UNUSED_BOT_UNIQUE", "history_messages": [
                 {"id": "m1", "role": "user", "content": "HISTORY_USER_UNIQUE"},
                 {"id": "m2", "role": "assistant", "content": "HISTORY_ASSISTANT_UNIQUE"}]}
    messages, _ = spec.build_messages(state)
    payload = messages[-1][1]
    assert payload.count("CURRENT_UNIQUE") == 1
    assert payload.count("QUOTE_UNIQUE") == 1
    assert "UNUSED_BOT_UNIQUE" not in payload
    decoded = json.loads(payload)
    assert decoded["sources"]["raw"] == "CURRENT_UNIQUE"
    if "history_messages" in spec.inputs:
        assert payload.count("HISTORY_USER_UNIQUE") == 1
        assert payload.count("HISTORY_ASSISTANT_UNIQUE") == 1
        assert decoded["source_roles"]["history:m2"] == "assistant"


def test_holding_system_is_independent_of_authorized_accounts():
    from app.subgraphs.close.holding_query import SPEC
    a, _ = SPEC.build_messages({"raw_text": "查持仓", "option_counterparties": [{"ctptyId": 1, "shortName": "甲"}]})
    b, _ = SPEC.build_messages({"raw_text": "查持仓", "option_counterparties": [{"ctptyId": 2, "shortName": "乙"}]})
    assert a[0] == b[0]
    assert a[1] != b[1]


@pytest.mark.parametrize("module_name,forbidden", [
    ("app.subgraphs.swap.place_order", "单位展开后的整数"),
    ("app.subgraphs.close.place_close", "比例 / 余额表达按规则换算"),
    ("app.subgraphs.close.holding_query", "99999999"),
])
def test_extraction_schema_does_not_request_computed_values(module_name, forbidden):
    model = importlib.import_module(module_name).CANDIDATE_MODEL
    wire = json.dumps(convert_to_openai_tool(model), ensure_ascii=False)
    assert forbidden not in wire
    assert "confidence" in wire and "evidence" in wire


def test_legacy_empty_tickers_do_not_mask_backend_error():
    from app.nodes.render import _render_branch
    _, decision = _render_branch({"product_type": "swap", "intent": "place_order_request",
        "place_params": {"orderList": [{"placeOrderWindCode": "未知证券"}]}, "tickers": [],
        "error": {"type": "BackendUnreachableError"}})
    assert decision == "error:backend_unreachable"


@pytest.mark.parametrize("product,factory", [("swap", "get_qwen_thinking"),
    ("option", "get_qwen_structured"), ("close", "get_qwen_thinking")])
async def test_empty_current_message_never_creates_history_only_evidence(monkeypatch, product, factory):
    from unittest.mock import MagicMock

    module = importlib.import_module(f"app.subgraphs.{product}.intent")
    llm = MagicMock(side_effect=AssertionError("empty source cannot authorize a model decision"))
    monkeypatch.setattr(module, factory, llm)
    result = await getattr(module, f"{product}_intent")({"raw_text": "", "quote_content": "确认下单"})
    assert not result.get("error")
    assert result["intent"] == "unknown_intent"
    llm.assert_not_called()


def test_active_requests_depend_on_business_input_not_wall_clock(monkeypatch):
    import datetime

    import app.graph.main  # noqa: F401 - register the actual business graph prompts
    from app.prompts.spec import all_specs

    specs = all_specs()
    assert len(specs) == 15
    assert not any(key.startswith("ticker/") for key in specs)
    state = {"raw_text": "2026年9月沪铜 买入100股", "quote_content": "引用原文",
             "bot_name": "UNUSED_BOT_UNIQUE"}
    before = {key: spec.build_messages(state) for key, spec in specs.items()}
    real = datetime.datetime

    class Later(real):
        @classmethod
        def now(cls, tz=None):
            return cls(2031, 1, 1, 12, 34, 56, tzinfo=tz)

    monkeypatch.setattr(datetime, "datetime", Later)
    after = {key: spec.build_messages(state) for key, spec in specs.items()}
    assert before == after
    for messages, _ in after.values():
        rendered = json.dumps(messages, ensure_ascii=False)
        assert "bot_name_list" not in rendered
        assert "UNUSED_BOT_UNIQUE" not in rendered


def test_migrated_golden_case_still_rejects_the_wrong_backend_security():
    from pathlib import Path

    from harness.differ import check_text_assertions
    from harness.golden import normalize_case

    rows = Path("tests/fixtures/categories/golden_option_inquiry_case.jsonl").read_text().splitlines()
    case = next(json.loads(row) for row in rows if json.loads(row).get("caseNo") == "case-021")
    turn = normalize_case(case, origin="golden_option_inquiry_case.jsonl:1").turns[0]
    reply = case["response_contains"]
    assert not check_text_assertions(reply, turn)
    assert check_text_assertions(reply.replace("600519.SH", "000001.SZ"), turn)
