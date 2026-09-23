"""从 swap 业务集派生标的识别数据集：订单数以卡片 `标的代码：` 行为准，表达从用户原文取。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import derive_instrument_fixtures as derive

CP = "11125测试短名（张天琪专用）"


def _case(send_text: str, codes: list[str], **overrides: object) -> dict:
    card = "-----场外收益互换详情-----\n" + "\n".join(
        f"标的代码：{code}\n标的名称：X\n委托方向：买入" for code in codes
    )
    case = {
        "caseNo": "ai_trade_assist_test_swap_fuzzy_target_recog_case_1",
        "name": "标的智能化识别案例1",
        "category": "swap_test_fuzzy_target_recog_data",
        "send_text": f"{send_text} {CP}",
        "at_bot": True,
        "quote_previous": False,
        "response_contains": card,
        "sub_scenes": [],
    }
    case.update(overrides)
    return case


def _derive(case: dict) -> dict:
    return derive.derive_case(case, source_stem="swap_test_fuzzy_target_recog_data", ignore_tokens=(CP,))


def test_fuzzy_name_with_market_hint() -> None:
    case = _derive(_case("港股市价买一百万京东", ["9618.HK"]))

    assert case["caseNo"] == "intent-swap-instrument-ai_trade_assist_test_swap_fuzzy_target_recog_case_1"
    assert case["category"] == "intent/swap"
    assert case["expected"]["product_type"] == "swap"
    assert case["expected"]["intent"] == "place_order_request"
    assert case["expected"]["instruments"] == [
        {"expression": ["京东"], "transaction_type": ["HK_STOCK"]}
    ]
    assert case["reference"] == {"backend_codes": ["9618.HK"]}
    assert "review" not in case
    assert "response_contains" not in case


def test_market_hint_absent_means_no_transaction_type_assertion() -> None:
    case = _derive(_case("市价买一百万京东", ["9618.HK"]))
    assert case["expected"]["instruments"] == [{"expression": ["京东"]}]


def test_market_hints_map_to_enum_candidates() -> None:
    assert derive.market_candidates("港股买入比亚迪") == ["HK_STOCK"]
    assert derive.market_candidates("A股百济神州限价14买100w") == ["A_SHARE"]
    assert derive.market_candidates("美股网易，限价10") == ["US_STOCK"]
    assert derive.market_candidates("深港通买入比亚迪") == ["SZ_HK_CONNECT"]
    assert derive.market_candidates("沪港通买入比亚迪") == ["SH_HK_CONNECT"]
    assert derive.market_candidates("市价买一百万京东") == []


def test_reviewed_hong_kong_cases_require_direct_hk_market() -> None:
    """用户裁决：只说港股不接受沪港通/深港通作为替代品种。"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures/intent/swap_instrument.jsonl"
    checked = 0
    for line in fixture.read_text().splitlines():
        case = json.loads(line)
        text = case["send_text"]
        if "港股" in text and not any(hint in text for hint in ("沪港通", "深港通")):
            checked += 1
            assert all(item.get("transaction_type") == ["HK_STOCK"]
                       for item in case["expected"]["instruments"]), case["caseNo"]
    assert checked > 0


def test_code_in_text_yields_code_name_and_combined_alternatives() -> None:
    case = _derive(_case("金力永磁300748.sz，全天均价卖出8万股，全部清仓。", ["300748.SZ"]))
    assert case["expected"]["instruments"] == [
        {"expression": ["金力永磁300748.sz", "300748.sz", "金力永磁"]}
    ]

    case = _derive(_case("300748 金力永磁，卖出，8万股（清仓），MKT，POV2%", ["300748.SZ"]))
    assert case["expected"]["instruments"] == [
        {"expression": ["300748 金力永磁", "300748", "金力永磁"]}
    ]

    case = _derive(_case("AAPL苹果市价 卖空100股", ["AAPL.O"]))
    assert case["expected"]["instruments"] == [{"expression": ["AAPL苹果", "AAPL", "苹果"]}]


def test_spaced_exchange_and_name_preserve_all_approved_alternatives() -> None:
    case = _derive(_case("1810 HK 小米集团 3080000 @15.6647", ["1810.HK"]))
    expressions = case["expected"]["instruments"][0]["expression"]
    assert expressions == ["1810 HK 小米集团", "1810 HK", "1810", "小米集团"]


def test_spaced_trading_word_is_not_an_exchange_suffix() -> None:
    case = _derive(_case("1810 MKT 买入100股", ["1810.HK"]))
    assert case["expected"]["instruments"] == [{"expression": ["1810"]}]


def test_split_orders_of_one_instrument_repeat_the_expression() -> None:
    case = _derive(
        _case("金力永磁300748.sz，集合竞价27.69元卖出3万股，开盘尽快卖出5万股，全部清仓。", ["300748.SZ", "300748.SZ"])
    )
    assert len(case["expected"]["instruments"]) == 2
    assert case["expected"]["instruments"][0] == case["expected"]["instruments"][1]


def test_multiple_tickers_follow_card_order() -> None:
    case = _derive(
        _case("沽出 MSTR 1704 股 @ 1524.033 NVDA 1961 股 @ 881.8628 TSM 13245 股 @ 140.5276", ["MSTR.O", "NVDA.O", "TSM.N"])
    )
    assert [item["expression"] for item in case["expected"]["instruments"]] == [["MSTR"], ["NVDA"], ["TSM"]]


def test_futures_contract_and_index_expressions() -> None:
    case = _derive(_case("买入开仓，GC2806合约，13手，不限价，ASAP", ["GCM28.CMX"]))
    assert case["expected"]["instruments"] == [{"expression": ["GC2806合约", "GC2806"]}]

    case = _derive(_case("恒生科技指数2706, 买入10手， @5,686", ["HTIF2706.HK"]))
    assert case["expected"]["instruments"] == [{"expression": ["恒生科技指数2706", "恒生科技指数"]}]


def test_backend_unresolved_still_takes_user_expression() -> None:
    """后端【待补充】不影响 LLM-only 口径：用户表达仍是期望值。"""
    case = _derive(_case("帮我买入100股International Drawdown Managed Eq，限价为10元，", ["【待补充】"]))
    assert "review" not in case
    assert case["expected"]["instruments"] == [{"expression": ["International Drawdown Managed Eq"]}]


def test_candidate_card_without_code_lines_uses_contains_any_as_reference() -> None:
    raw = _case("市价买一百万京东", [])
    raw["response_contains"] = "-----场外收益互换详情-----\n委托方向：买入"
    raw["response_contains_any"] = "9618.HK\n89618.HK\nJD.O\n"
    case = _derive(raw)
    assert case["expected"]["instruments"] == [{"expression": ["京东"]}]
    assert case["reference"] == {"backend_codes": ["9618.HK", "89618.HK", "JD.O"]}


def test_missing_expression_is_marked_pending() -> None:
    case = _derive(_case("买入 25000股 限价300", ["IBM.N"]))
    assert case["review"]["status"] == "pending"
    assert case["expected"]["instruments"][0]["expression"] == []


def test_colloquial_and_traditional_noise_is_stripped() -> None:
    assert _derive(_case("3939hk 暫買入 38000 股 @ 7.4747", ["3939.HK"]))["expected"]["instruments"] == [{"expression": ["3939hk"]}]
    assert _derive(_case("京东集团-sw  空29万股  市价跟5%", ["9618.HK"]))["expected"]["instruments"] == [{"expression": ["京东集团-sw", "京东集团"]}]
    assert _derive(_case("买入开仓 000993 神火股份 64万股 POV10%市价", ["000933.SZ"]))["expected"]["instruments"] == [{"expression": ["000993 神火股份", "000993", "神火股份"]}]
    assert _derive(_case("9901 暫買入 45000@ 41.07167， 325 暫買入 39300@133.7282", ["9901.HK", "0325.HK"]))["expected"]["instruments"] == [{"expression": ["9901"]}, {"expression": ["325"]}]
    assert _derive(_case("麻烦继续挂单486平仓500股腾讯", ["0700.HK"]))["expected"]["instruments"] == [{"expression": ["腾讯"]}]


def test_write_drafts_filters_pending_and_keeps_intent_fields(tmp_path: Path) -> None:
    source = tmp_path / "swap_test_fuzzy_target_recog_data.jsonl"
    rows = [
        _case("港股市价买一百万京东", ["9618.HK"]),
        _case("买入 25000股 限价300", ["IBM.N"], caseNo="c2"),
    ]
    source.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    out = tmp_path / "swap_instrument.jsonl"
    summary = derive.write_cases([source], out, ignore_tokens=(CP,), only_reviewed=True)
    assert summary == {"written": 1, "pending": 1}
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert record["type"] == "positive"
    assert record["source"].startswith("derived:swap_test_fuzzy_target_recog_data#")
