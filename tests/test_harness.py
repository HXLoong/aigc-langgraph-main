"""Tests for the categories-based harness contract."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from harness import cli as cli_module
from harness.cli import build_parser
from harness.differ import (
    check_structured_assertions,
    check_text_assertions,
    diff_fields,
    is_pass,
)
from harness.golden import (
    GoldenCase,
    filter_by_category,
    index_by_category,
    load_golden,
)
from harness.multi_turn import run_case_multi

ROOT = Path(__file__).resolve().parents[1]


def test_load_categories_total() -> None:
    cases = load_golden()
    assert len(cases) == 389


def test_option_case_is_multiturn() -> None:
    case = next(case for case in load_golden() if case.id == "case-025")
    assert len(case.turns) == 4
    assert case.turns[0].quote_previous is None
    assert case.turns[1].quote_previous is True


def test_swap_case_normalizes_multiline_assertions() -> None:
    case = next(case for case in load_golden() if case.category == "swap_prod_data")
    assert case.id == case.case_no
    assert case.turns[0].response_contains
    assert len(case.turns[0].response_contains) > 1
    assert case.expected == {}


def test_index_and_filter() -> None:
    cases = load_golden()
    assert len(filter_by_category(cases, "option")) == 13
    assert set(index_by_category(cases)) >= {"swap_prod_data", "option/inquiry"}


def test_loader_rejects_legacy_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.jsonl"
    path.write_text('{"id":"x","conversation":[{"raw_content":"x"}]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="legacy fields"):
        load_golden(path)


def test_differ_excludes_output() -> None:
    assert is_pass(diff_fields({"output": "human text"}, {"output": "different"}))


def test_text_assertions_support_all_any_and_not_contains() -> None:
    from harness.golden import TurnSpec

    spec = TurnSpec(
        send_text="x",
        response_contains=["order"],
        response_contains_any=["A", "B"],
        response_not_contains=["error"],
    )
    assert not check_text_assertions("order B", spec)
    assert check_text_assertions("order error", spec)


def test_structured_assertions_compare_expected_fields() -> None:
    assert not check_structured_assertions(
        {"product_type": "swap", "intent": "place_order_request"},
        {"product_type": "swap", "intent": "place_order_request"},
    )
    assert check_structured_assertions({"product_type": "option"}, {"product_type": "swap"})


def test_structured_assertions_map_winners_to_ticker_codes() -> None:
    """R1：fixture 期望 winners，HTTP outputs 只有 tickers[].wind_code。"""
    assert not check_structured_assertions(
        {"tickers": [{"wind_code": "600519.SH", "from_goats": True}]},
        {"winners": ["600519.SH"]},
    )
    # 集合语义：忽略顺序、去重
    assert not check_structured_assertions(
        {"tickers": [{"wind_code": "600519.SH"}, {"wind_code": "300750.SZ"}]},
        {"winners": ["300750.SZ", "600519.SH", "300750.SZ"]},
    )
    assert check_structured_assertions(
        {"tickers": [{"wind_code": "601398.SH"}]},
        {"winners": ["600519.SH"]},
    )


def test_structured_assertions_winners_keeps_other_keys_direct() -> None:
    """R1：winners 之外的键仍按 diff_fields 直比；expected 无 winners 时跳过特判。"""
    assert check_structured_assertions(
        {"tickers": [{"wind_code": "600519.SH"}], "product_type": "swap"},
        {"winners": ["600519.SH"], "product_type": "option"},
    )
    assert not check_structured_assertions(
        {"product_type": "option", "tickers": [{"wind_code": "600519.SH"}]},
        {"product_type": "option"},
    )


def _stub_cli_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """把 harness.cli 内的 httpx.AsyncClient 指向 MockTransport。"""

    def factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=str(kwargs["base_url"])
        )

    monkeypatch.setattr(
        cli_module, "httpx", SimpleNamespace(HTTPError=httpx.HTTPError, AsyncClient=factory)
    )


@pytest.mark.asyncio
async def test_doctor_tolerates_mysql_only_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(503, json={"checks": {"mysql": "fail", "llm": "ok"}})

    _stub_cli_httpx(monkeypatch, handler)
    assert await cli_module._doctor("http://test", "none") == 0
    assert await cli_module._doctor("http://test", "mysql") == 2


@pytest.mark.asyncio
async def test_run_blocks_when_gate_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_gate(base_url: str, checkpoint: str = "none") -> int:
        return 2

    monkeypatch.setattr(cli_module, "_doctor", failing_gate)
    args = build_parser().parse_args(["run", "--user-id", "u", "--room-id", "r"])
    assert await cli_module._run(args) == 2


def test_resolve_eval_ids_prefers_explicit_then_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module, "_dotenv_values", lambda: {"EVAL_USER_ID": "env-u", "EVAL_ROOM_ID": "env-r"}
    )
    assert cli_module._resolve_eval_ids("cli-u", "cli-r") == ("cli-u", "cli-r")
    assert cli_module._resolve_eval_ids(None, None) == ("env-u", "env-r")
    assert cli_module._resolve_eval_ids("cli-u", None) == ("cli-u", "env-r")


@pytest.mark.asyncio
async def test_run_requires_eval_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async def passing_gate(base_url: str, checkpoint: str = "none") -> int:
        return 0

    monkeypatch.setattr(cli_module, "_doctor", passing_gate)
    monkeypatch.setattr(cli_module, "_dotenv_values", lambda: {})
    args = build_parser().parse_args(["run"])
    args.user_id, args.room_id = "", ""
    assert await cli_module._run(args) == 2


@pytest.mark.asyncio
async def test_http_multiturn_reuses_conversation_and_quote() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        import json

        payload = json.loads(body)
        requests.append(payload)
        turn = len(requests)
        return httpx.Response(
            200,
            json={
                "data": {
                    "status": "succeeded",
                    "outputs": {
                        "reply_text": f"reply-{turn}",
                        "product_type": "option",
                        "intent": "new_inquiry",
                    },
                }
            },
        )

    case = GoldenCase(
        id="http-1",
        category="option/inquiry",
        turns=[
            {"send_text": "first", "at_bot": True},
            {"send_text": "second", "quote_previous": True},
        ],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_case_multi(
            case,
            base_url="http://test",
            user_id="user",
            room_id="room",
            client=client,
        )
    assert len(result.turns) == 2
    assert requests[0]["conversation_id"] == requests[1]["conversation_id"]
    assert requests[1]["inputs"]["quote_content"] == "reply-1"
    assert requests[0]["inputs"]["at_bot"] is True


def test_cli_parser_uses_http_contract() -> None:
    args = build_parser().parse_args(
        ["run", "--base-url", "http://127.0.0.1:8000", "--backend", "real"]
    )
    assert args.base_url == "http://127.0.0.1:8000"
    assert args.backend == "real"
    assert args.checkpoint == "none"
