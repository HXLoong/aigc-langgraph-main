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
    check_case_assertions,
    check_structured_assertions,
    check_text_assertions,
    diff_fields,
    is_pass,
)
from harness.golden import (
    GoldenCase,
    build_overview,
    filter_by_category,
    index_by_category,
    load_golden,
    select_runnable,
)
from harness.multi_turn import run_case_multi

ROOT = Path(__file__).resolve().parents[1]


def test_load_categories_total() -> None:
    cases = load_golden(ROOT / "tests" / "fixtures" / "categories")
    assert len(cases) == 389
    assert all(case.dialect == "a" for case in cases)


def test_default_discovery_includes_unified_b_dialect() -> None:
    """ADR 0024 D6：B 方言（unified_golden.jsonl，921 条 / 251 多轮）并入 harness 默认发现，
    可执行样本 389 → 1310、多轮 9 → 260。"""
    cases = load_golden()
    assert len(cases) == 1310
    assert sum(1 for case in cases if len(case.turns) > 1) == 260
    assert sum(1 for case in cases if case.dialect == "b") == 921
    assert len({case.id for case in cases}) == 1310, "两方言 id 不得冲突"
    runnable, skipped = select_runnable(cases)
    # 48 条 B case 某轮 raw_content 为空（用户文本写进了 quote_desc，Issue #113）：加载计数、不执行
    assert len(skipped) == 48 and all(case.dialect == "b" for case in skipped)
    assert len(runnable) == 1262


def test_b_dialect_empty_raw_content_marks_case_unrunnable(tmp_path: Path) -> None:
    case = load_golden(_write(tmp_path, {
        "id": "opt-177", "category": "option_close/place",
        "expected": {"product_type": "option_close", "intent": "close_order_request", "output": ""},
        "conversation": [{"raw_content": "我想平仓", "quote_desc": ""}, {"raw_content": "", "quote_desc": "引用上一条机器人消息"}],
    }))[0]
    assert case.skip_reason.startswith("conversation[1] has empty raw_content")
    assert select_runnable([case]) == ([], [case])


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
    cases = load_golden(ROOT / "tests" / "fixtures" / "categories")
    assert len(filter_by_category(cases, "option")) == 13
    assert set(index_by_category(cases)) >= {"swap_prod_data", "option/inquiry"}


def _write(tmp_path: Path, *rows: dict) -> Path:
    import json

    path = tmp_path / "b.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def test_b_dialect_multiturn_maps_conversation_to_turns(tmp_path: Path) -> None:
    """B 方言：conversation[].raw_content → send_text；后续轮 quote_desc 非空 → 引用上一轮回复；
    case 级 expected 描述的是整段对话中的焦点轮（swap/confirm 是末轮、option/place_from_quote
    是中间轮），所以多轮时不落到任何一轮，改为 any_turn 作用域。"""
    case = load_golden(_write(tmp_path, {
        "id": "swap-222", "category": "swap/confirm", "type": "positive", "source": "business_seed",
        "expected": {"product_type": "swap", "intent": "confirm_order", "output": "机器人确认下单"},
        "conversation": [
            {"raw_content": "A组合 HTIF2504 空 1657股 市价", "quote_desc": ""},
            {"raw_content": "确认下单", "quote_desc": "用户引用上一条机器人消息"},
        ],
    }))[0]
    assert case.dialect == "b"
    assert case.category == "swap/confirm"
    assert [turn.send_text for turn in case.turns] == ["A组合 HTIF2504 空 1657股 市价", "确认下单"]
    assert case.turns[0].at_bot is True and case.turns[0].quote_previous is None
    assert case.turns[1].at_bot is False and case.turns[1].quote_previous is True
    assert case.turns[1].quote_desc == "用户引用上一条机器人消息"
    assert case.expected_scope == "any_turn"
    assert all(turn.expected == {} for turn in case.turns)
    assert case.expected == {"product_type": "swap", "intent": "confirm_order", "output": "机器人确认下单"}
    assert case.expected_output == "机器人确认下单"


def test_b_dialect_single_turn_asserts_on_first_turn(tmp_path: Path) -> None:
    case = load_golden(_write(tmp_path, {
        "id": "opt-001", "category": "option/inquiry", "type": "negative", "source": "business_seed",
        "expected": {"product_type": "option", "intent": "new_inquiry", "output": "提示参数不完整"},
        "conversation": [{"raw_content": "参与型看涨 腾讯控股 1个月", "quote_desc": ""}],
    }))[0]
    assert case.expected_scope == "first_turn"
    assert case.turns[0].expected == {"product_type": "option", "intent": "new_inquiry", "output": "提示参数不完整"}


def test_b_dialect_first_turn_quote_desc_is_kept_but_not_replayable(tmp_path: Path) -> None:
    """198 条 B case 首轮就标注引用（上下文依赖 case）：首轮无上一轮回复可引，
    quote_previous 保持 None，quote_desc 留在 TurnSpec 供概览与人工判读。"""
    case = load_golden(_write(tmp_path, {
        "id": "opt-057", "category": "unknown",
        "expected": {"product_type": "option", "intent": "unknown_intent", "output": ""},
        "conversation": [{"raw_content": "123456789", "quote_desc": "机器人返回：贵州茅台欧式看涨期权"}],
    }))[0]
    assert case.turns[0].quote_previous is None
    assert case.turns[0].quote_desc == "机器人返回：贵州茅台欧式看涨期权"
    assert "机器人返回" in build_overview(case)


def test_raw_content_single_turn_dialect(tmp_path: Path) -> None:
    case = load_golden(_write(tmp_path, {
        "id": "tk001", "category": "ticker", "raw_content": "腾讯 1000 股", "expected": {"winners": ["00700.HK"]},
    }))[0]
    assert case.dialect == "raw"
    assert case.turns[0].send_text == "腾讯 1000 股"
    assert case.turns[0].expected == {"winners": ["00700.HK"]}


def test_loader_rejects_mixed_dialects(tmp_path: Path) -> None:
    path = _write(tmp_path, {"id": "x", "send_text": "a", "conversation": [{"raw_content": "b"}]})
    with pytest.raises(ValueError, match="mixed"):
        load_golden(path)


def test_b_dialect_requires_raw_content_per_turn(tmp_path: Path) -> None:
    path = _write(tmp_path, {"id": "x", "conversation": [{"raw_content": "a"}, {"quote_desc": "引用"}]})
    with pytest.raises(ValueError, match=r"conversation\[1\].*raw_content"):
        load_golden(path)


def test_case_level_any_turn_assertion_passes_when_some_turn_matches() -> None:
    expected = {"product_type": "swap", "intent": "confirm_order", "output": "x"}
    turns = [
        {"product_type": "swap", "intent": "place_order_request"},
        {"product_type": "swap", "intent": "confirm_order"},
    ]
    assert not check_case_assertions(turns, expected)
    diffs = check_case_assertions(turns[:1], expected)
    assert [d.path for d in diffs] == ["case.expected"]
    assert diffs[0].expected == {"product_type": "swap", "intent": "confirm_order"}
    assert diffs[0].actual == [{"product_type": "swap", "intent": "place_order_request"}]


def _outcome(index: int, product_type: str, intent: str):
    from harness.multi_turn import TurnOutcome

    outputs = {"product_type": product_type, "intent": intent, "reply_text": f"r{index}"}
    return TurnOutcome(
        index=index, scene="", send_text=f"t{index}", at_bot=index == 1, quote_passed="",
        reply_text=f"r{index}", product_type=product_type, intent=intent, tickers=[],
        place_params=None, api_code=0, api_result=None, error=None, trace="", outputs=outputs,
    )


def test_cli_turn_diffs_apply_any_turn_scope_to_executed_turns() -> None:
    from harness.multi_turn import MultiTurnResult

    case = GoldenCase(
        id="swap-222", category="swap/confirm", expected_scope="any_turn",
        expected={"product_type": "swap", "intent": "confirm_order", "output": "x"},
        turns=[{"send_text": "a"}, {"send_text": "b", "quote_previous": True}],
    )
    ok = MultiTurnResult(case_id="swap-222", conversation_id="c", turns=[
        _outcome(1, "swap", "place_order_request"), _outcome(2, "swap", "confirm_order"),
    ])
    assert not any(cli_module._turn_diffs(case, ok).values())

    bad = MultiTurnResult(case_id="swap-222", conversation_id="c", turns=[
        _outcome(1, "swap", "place_order_request"), _outcome(2, "swap", "place_order_request"),
    ])
    diffs = cli_module._turn_diffs(case, bad)
    assert [d.path for d in diffs["case"]] == ["case.expected"]


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
    """R1：fixture 期望 winners，HTTP outputs 的 tickers[] 按 wire alias 输出 windCode。"""
    assert not check_structured_assertions(
        {"tickers": [{"windCode": "600519.SH", "from_goats": True}]},
        {"winners": ["600519.SH"]},
    )
    # 集合语义：忽略顺序、去重
    assert not check_structured_assertions(
        {"tickers": [{"windCode": "600519.SH"}, {"windCode": "300750.SZ"}]},
        {"winners": ["300750.SZ", "600519.SH", "300750.SZ"]},
    )
    assert check_structured_assertions(
        {"tickers": [{"windCode": "601398.SH"}]},
        {"winners": ["600519.SH"]},
    )


def test_structured_assertions_winners_use_real_ticker_wire_shape() -> None:
    """契约测试：outputs.tickers 必须按 TickerCandidate.model_dump()（by_alias）真实形状比对，
    防止 differ 再次固化 snake_case 别名（ADR 0024 阶段 0）。"""
    from app.graph.state import TickerCandidate

    dumped = TickerCandidate(windCode="600519.SH", from_goats=True).model_dump()
    assert "windCode" in dumped and "wind_code" not in dumped
    assert not check_structured_assertions({"tickers": [dumped]}, {"winners": ["600519.SH"]})


def test_structured_assertions_winners_keeps_other_keys_direct() -> None:
    """R1：winners 之外的键仍按 diff_fields 直比；expected 无 winners 时跳过特判。"""
    assert check_structured_assertions(
        {"tickers": [{"windCode": "600519.SH"}], "product_type": "swap"},
        {"winners": ["600519.SH"], "product_type": "option"},
    )
    assert not check_structured_assertions(
        {"product_type": "option", "tickers": [{"windCode": "600519.SH"}]},
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


def _health_handler(backend_mode: str | None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            body: dict = {"status": "ok"}
            if backend_mode is not None:
                body["backend_mode"] = backend_mode
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"status": "ok", "checks": {"mysql": "ok"}})

    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server_mode", "wanted", "code"),
    [
        ("real", "real", 0),
        ("real", "mock", 0),
        ("dry-run", "dry-run", 0),
        ("real", "dry-run", 2),  # 想 dry-run 却打在真后端 → 会真下单，必须拦
        ("dry-run", "real", 2),  # 想跑真回归却打在 dry-run → 结果是假的，必须拦
        (None, "dry-run", 2),  # 旧服务端不报模式，dry-run 不能假定安全
        (None, "real", 0),
    ],
)
async def test_doctor_gates_backend_mode(
    monkeypatch: pytest.MonkeyPatch, server_mode: str | None, wanted: str, code: int
) -> None:
    """ADR 0024 D6：`--backend` 不再只是打印警告，而是对照服务端 /health.backend_mode 把关。"""
    _stub_cli_httpx(monkeypatch, _health_handler(server_mode))
    assert await cli_module._doctor("http://test", "none", backend=wanted) == code


def test_text_assertions_tolerate_dry_run_marker_only_when_asked() -> None:
    spec = GoldenCase(id="x", category="swap", turns=[{"send_text": "a"}]).turns[0]
    assert check_text_assertions("下单成功 DRY-RUN-place_order_request", spec)
    assert not check_text_assertions("下单成功 DRY-RUN-place_order_request", spec, allow_dry_run=True)


def _result(case: GoldenCase, turns: list, failure: dict | None = None):
    from harness.multi_turn import MultiTurnResult

    return MultiTurnResult(
        case_id=case.id, conversation_id="c", turns=turns, failure=failure,
        remaining_turns=len(case.turns) - len(turns),
    )


def test_report_buckets_business_reject_separately() -> None:
    """D6：业务拒绝不算 PASS，单独成桶 REJECTED；有 diff 的仍是 FAIL。"""
    case = GoldenCase(id="opt-1", category="option/inquiry", turns=[{"send_text": "a"}])
    reject = {"turn": 1, "kind": "business_reject", "api_code": 400, "api_result": "参数缺失"}
    result = _result(case, [_outcome(1, "option", "new_inquiry")], failure=reject)
    report = cli_module._report_case(case, result, cli_module._turn_diffs(case, result))
    assert report["status"] == "REJECTED" and report["passed"] is False

    ok = _result(case, [_outcome(1, "option", "new_inquiry")])
    assert cli_module._report_case(case, ok, cli_module._turn_diffs(case, ok))["status"] == "PASS"

    case_with_expect = GoldenCase(
        id="opt-2", category="option/inquiry", expected={"intent": "confirm_order"},
        turns=[{"send_text": "a", "expected": {"intent": "confirm_order"}}],
    )
    bad = _result(case_with_expect, [_outcome(1, "option", "new_inquiry")], failure=reject)
    report = cli_module._report_case(case_with_expect, bad, cli_module._turn_diffs(case_with_expect, bad))
    assert report["status"] == "FAIL"


def test_unexecuted_turns_after_early_stop_are_explicit_failures() -> None:
    """D6：早停后未执行的轮次逐轮记 runtime 失败，多轮 case 不能因早停而静默通过。"""
    case = GoldenCase(
        id="opt-3", category="option/place_from_quote",
        turns=[{"send_text": "a"}, {"send_text": "b", "quote_previous": True}, {"send_text": "c", "quote_previous": True}],
    )
    reject = {"turn": 1, "kind": "business_reject", "api_code": 400, "api_result": "x"}
    result = _result(case, [_outcome(1, "option", "new_inquiry")], failure=reject)
    diffs = cli_module._turn_diffs(case, result)
    assert diffs[1] == []
    assert [d.path for d in diffs[2]] == ["runtime"] and [d.path for d in diffs[3]] == ["runtime"]
    assert "early stop at turn 1 (business_reject)" in diffs[2][0].actual
    assert cli_module._report_case(case, result, diffs)["status"] == "FAIL"

    tech = {"turn": 1, "kind": "technical_error", "error": {"type": "ConnectError", "message": "refused"}}
    result = _result(case, [], failure=tech)
    diffs = cli_module._turn_diffs(case, result)
    assert sorted(diffs) == [1, 2, 3] and all(d[0].path == "runtime" for d in diffs.values())


def test_summary_and_markdown_count_rejected_bucket() -> None:
    reports = [
        {"case_id": "a", "category": "c", "status": "PASS", "passed": True, "failure": None},
        {"case_id": "b", "category": "c", "status": "REJECTED", "passed": False, "failure": {"kind": "business_reject"}},
        {"case_id": "d", "category": "c", "status": "FAIL", "passed": False, "failure": None},
    ]
    summary = cli_module._summarize(reports)
    assert (summary["passed"], summary["rejected"], summary["failed"]) == (1, 1, 1)
    assert summary["pass_rate"] == 1 / 3
    md = cli_module._render_markdown(reports)
    assert "- REJECTED: 1" in md and "| `b` | `c` | REJECTED |" in md


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
    async def failing_gate(base_url: str, checkpoint: str = "none", **_: object) -> int:
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
    async def passing_gate(base_url: str, checkpoint: str = "none", **_: object) -> int:
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
