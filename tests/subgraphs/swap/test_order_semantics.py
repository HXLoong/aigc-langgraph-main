"""Order-local source evidence distinguishes instructions from position descriptions."""
from __future__ import annotations

import pytest

from app.extraction.candidates import candidate_model, verify_candidates
from app.extraction.fields import EvidenceError
from app.subgraphs.swap.candidate_scope import constrain_candidates
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates, normalize_field


def cell(value: str, evidence: str | None = None, origin: str = "raw") -> dict:
    return {"value": value, "evidence": evidence or value, "origin": origin, "confidence": .95}


def run(raw: str, rows: list[dict], quote: str = ""):
    candidates = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": rows})
    sources = {"raw": raw, "quote": quote}
    verify_candidates(candidates, sources)
    scoped = constrain_candidates(candidates, sources)
    verify_candidates(scoped, sources)
    return normalize_candidates(scoped, sources)


def test_sell_all_holdings_uses_same_order_action_evidence():
    raw = "甲证券，卖出，80000股 甲账户全部持仓，MKT，POV1%"
    params, records = run(raw, [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("80000股"),
        "placeOrderOrderDirection": cell("卖出"),
        "placeOrderCloseIntent": cell("全部持仓"),
        "placeOrderAlgorithmType": cell("POV1%"), "placeOrderPriceType": cell("MKT"),
    }])
    order = params.order_list[0]
    assert order.place_order_order_direction == "SELL"
    assert order.place_order_quantity == 80000
    assert order.place_order_close_intent is True
    assert order.place_order_entrust_ratio == 1
    assert order.place_order_algorithm_type == "POV"
    assert order.place_order_pov_percent == 1
    assert records["swap/place_order.orderList.0.placeOrderCloseIntent"].evidence == raw
    ratio = records["swap/place_order.orderList.0.placeOrderEntrustRatio"]
    assert ratio.source == "inferred" and ratio.derived_from


def test_position_description_does_not_invent_action_or_clock_time():
    raw = "甲证券 剩余全部持仓 80000股 请VWAP全天 市价执行"
    params, _ = run(raw, [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("80000股"),
        "placeOrderOrderDirection": cell("剩余全部持仓"),
        "placeOrderCloseIntent": cell("剩余全部持仓"),
        "placeOrderAlgorithmType": cell("VWAP全天"),
        "placeOrderRelativeTimeMinutes": cell("全天"),
        "placeOrderEndTime": cell("全天"), "placeOrderPriceType": cell("市价"),
    }])
    order = params.order_list[0]
    assert order.place_order_wind_code == "甲证券"
    assert order.place_order_order_direction is None
    assert order.place_order_close_intent is None
    assert order.place_order_entrust_ratio is None
    assert order.place_order_algorithm_type == "VWAP"
    assert order.place_order_relative_time_minutes is None
    assert order.place_order_end_time is None


def test_other_order_action_cannot_enable_close_for_bare_holdings():
    raw = "甲证券 卖出200股 全部清仓；乙证券 剩余全部持仓100股 VWAP全天"
    params, _ = run(raw, [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("200股"),
         "placeOrderOrderDirection": cell("卖出"), "placeOrderCloseIntent": cell("全部清仓")},
        {"placeOrderWindCode": cell("乙证券"), "placeOrderQuantity": cell("100股"),
         "placeOrderCloseIntent": cell("剩余全部持仓"),
         "placeOrderAlgorithmType": cell("VWAP全天")},
    ])
    assert params.order_list[0].place_order_close_intent is True
    assert params.order_list[1].place_order_close_intent is None
    assert params.order_list[1].place_order_order_direction is None


def test_action_evidence_from_another_order_is_rejected():
    with pytest.raises(EvidenceError):
        run("甲证券 全部清仓；乙证券 买入100股", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderCloseIntent": cell("全部清仓")},
            {"placeOrderWindCode": cell("乙证券"), "placeOrderCloseIntent": cell("全部清仓")},
        ])


def test_quoted_action_cannot_enable_current_holdings_description():
    params, _ = run("甲证券 剩余全部持仓100股", [{
        "placeOrderWindCode": cell("甲证券"),
        "placeOrderCloseIntent": cell("剩余全部持仓"),
    }], quote="甲证券全部清仓")
    assert params.order_list[0].place_order_close_intent is None


@pytest.mark.parametrize("raw", [
    "甲证券 如果卖出全部持仓", "甲证券 卖出全部持仓或只卖一半",
])
def test_conditional_or_alternative_full_close_is_not_inferred(raw):
    with pytest.raises(ValueError):
        run(raw, [{"placeOrderWindCode": cell("甲证券"),
                   "placeOrderOrderDirection": cell("卖出"),
                   "placeOrderCloseIntent": cell("全部持仓")}])


def test_negated_full_close_is_not_positive_close():
    params, _ = run("甲证券 不要卖出全部持仓", [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderCloseIntent": cell("全部持仓"),
    }])
    assert params.order_list[0].place_order_close_intent is False
    assert params.order_list[0].place_order_entrust_ratio is None


@pytest.mark.parametrize("value,expected", [("POV1%", "POV"), ("VWAP全天", "VWAP"),
                                             ("vwap到收盘", "VWAP"), ("TWAP 全天", "TWAP")])
def test_algorithm_with_explicit_suffix(value, expected):
    assert normalize_field("placeOrderAlgorithmType", value) == expected


@pytest.mark.parametrize("value", ["稳健", "POV0%", "POV101%", "POV-1%", "不要POV1%",
                                     "TWAP或VWAP", "POV1%/2%", "VWAPX", "POV1%买入"])
def test_algorithm_unknown_conflicting_or_invalid_suffix_stays_error(value):
    with pytest.raises(ValueError):
        normalize_field("placeOrderAlgorithmType", value)


def test_embedded_algorithm_ratio_must_agree_with_explicit_ratio():
    with pytest.raises(ValueError, match="冲突"):
        run("甲证券 POV1% 跟量2%", [{
            "placeOrderWindCode": cell("甲证券"), "placeOrderAlgorithmType": cell("POV1%"),
            "placeOrderPovPercent": cell("2%"),
        }])


def test_negated_direction_cannot_be_used_as_a_positive_sell():
    with pytest.raises(ValueError, match="否定"):
        run("甲证券 不要卖出全部持仓", [{
            "placeOrderWindCode": cell("甲证券"),
            "placeOrderOrderDirection": cell("卖出"),
            "placeOrderCloseIntent": cell("全部持仓"),
        }])


async def test_semantic_filter_trace_records_fields_without_business_text(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.subgraphs.swap import place_order

    candidates = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderWindCode": cell("甲证券"),
        "placeOrderCloseIntent": cell("剩余全部持仓"),
        "placeOrderEndTime": cell("全天"),
    }]})
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=candidates)
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: llm)
    result = await place_order.swap_extract_candidates({"raw_text": "甲证券 剩余全部持仓 VWAP全天"})
    entry = next(e for e in result["trace"] if e.node == "swap_extract_candidates")
    assert entry.llm_output["candidate_changes"] == [
        {"field": "orderList.0.placeOrderEndTime", "change": "omitted"},
        {"field": "orderList.0.placeOrderCloseIntent", "change": "omitted"},
    ]
    assert "甲证券" not in str(entry.llm_output)


async def test_normalization_error_identifies_field():
    from app.subgraphs.swap.place_order import swap_normalize

    candidates = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderQuantity": cell("约一万股"),
    }]})
    result = await swap_normalize({"raw_text": "约一万股", "sp_candidates": candidates.model_dump(by_alias=True)})
    assert result["error"].node == "swap_normalize"
    assert "placeOrderQuantity" in result["error"].message


@pytest.mark.parametrize("separator", ["，", "；"])
def test_close_claim_cannot_borrow_first_order_evidence(separator):
    with pytest.raises(EvidenceError):
        run(f"甲证券 卖出全部持仓{separator}乙证券 剩余持仓", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderCloseIntent": cell("卖出全部持仓")},
            {"placeOrderWindCode": cell("乙证券"),
             "placeOrderCloseIntent": cell("全部持仓", "甲证券 卖出全部持仓")},
        ])


def test_algorithm_claim_cannot_borrow_another_order_evidence():
    with pytest.raises(EvidenceError):
        run("甲证券 卖出100股 POV1%；乙证券 买入200股 TWAP全天", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderAlgorithmType": cell("POV1%")},
            {"placeOrderWindCode": cell("乙证券"), "placeOrderAlgorithmType": cell("POV1%")},
        ])


@pytest.mark.parametrize("raw", ["甲证券 不要把全部持仓卖出", "甲证券 别将全部持仓平仓"])
def test_negation_with_object_before_action_is_not_positive_close(raw):
    params, _ = run(raw, [{"placeOrderWindCode": cell("甲证券"),
                           "placeOrderCloseIntent": cell("全部持仓")}])
    assert params.order_list[0].place_order_close_intent is False


@pytest.mark.parametrize("value", ["卖出全部持仓", "POV1%"])
def test_short_candidate_evidence_cannot_hide_negated_source(value):
    field = "placeOrderAlgorithmType" if value.startswith("POV") else "placeOrderCloseIntent"
    if field == "placeOrderAlgorithmType":
        with pytest.raises(ValueError):
            run("甲证券 不要" + value, [{"placeOrderWindCode": cell("甲证券"), field: cell(value)}])
    else:
        params, _ = run("甲证券 不要" + value, [{"placeOrderWindCode": cell("甲证券"), field: cell(value)}])
        assert params.order_list[0].place_order_close_intent is False


def test_short_candidate_evidence_cannot_hide_conditional_source():
    with pytest.raises(ValueError):
        run("甲证券 如果卖出全部持仓", [{"placeOrderWindCode": cell("甲证券"),
                                      "placeOrderCloseIntent": cell("卖出全部持仓")}])


def test_holding_ratio_without_an_action_is_not_order_ratio():
    params, _ = run("甲证券 剩余一半持仓", [{"placeOrderWindCode": cell("甲证券"),
                                          "placeOrderEntrustRatio": cell("一半持仓")}])
    assert params.order_list[0].place_order_entrust_ratio is None


@pytest.mark.parametrize("value,raw", [("34250", "甲证券 卖出 -34250"),
                                        ("34250股", "甲证券 卖出 -34250股")])
def test_quantity_candidate_cannot_drop_the_original_negative_sign(value, raw):
    from app.subgraphs.swap.errors import NonPositiveQuantityError

    with pytest.raises(NonPositiveQuantityError):
        run(raw, [{"placeOrderWindCode": cell("甲证券"),
                   "placeOrderQuantity": cell(value), "placeOrderOrderDirection": cell("卖出")}])


def test_market_price_word_does_not_negate_the_sell_action():
    params, _ = run("甲证券 不限价卖出全部持仓", [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
        "placeOrderCloseIntent": cell("全部持仓"), "placeOrderPriceType": cell("不限价"),
    }])
    assert params.order_list[0].place_order_order_direction == "SELL"
    assert params.order_list[0].place_order_close_intent is True
    assert params.order_list[0].place_order_price_type == "MarketOrder"


def test_sell_fragment_requires_same_order_holding_evidence_for_close():
    params, _ = run("甲证券，卖出，80000股，全部持仓", [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("80000股"),
        "placeOrderOrderDirection": cell("卖出"), "placeOrderCloseIntent": cell("卖出"),
        "placeOrderEntrustRatio": cell("全部持仓"),
    }])
    assert params.order_list[0].place_order_close_intent is True
    assert params.order_list[0].place_order_entrust_ratio == 1
    with pytest.raises(ValueError):
        normalize_field("placeOrderCloseIntent", "卖出", "卖出80000股")


@pytest.mark.parametrize("separator", ["；", "，"])
def test_second_order_window_keeps_negation_before_its_ticker(separator):
    params, _ = run(f"甲证券 卖出全部持仓{separator}不要把乙证券全部持仓卖出", [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderCloseIntent": cell("全部持仓")},
        {"placeOrderWindCode": cell("乙证券"), "placeOrderCloseIntent": cell("全部持仓")},
    ])
    assert params.order_list[0].place_order_close_intent is True
    assert params.order_list[1].place_order_close_intent is False
    assert params.order_list[1].place_order_entrust_ratio is None


def test_missing_second_candidate_does_not_expand_first_order_scope():
    with pytest.raises(EvidenceError):
        run("甲证券 剩余100股持仓；乙证券 卖出全部持仓", [{
            "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("100股"),
            "placeOrderOrderDirection": cell("卖出"), "placeOrderCloseIntent": cell("全部持仓"),
        }])


def test_quantity_candidate_whitespace_cannot_hide_negative_sign():
    from app.subgraphs.swap.errors import NonPositiveQuantityError

    with pytest.raises(NonPositiveQuantityError):
        run("甲证券 卖出 - 34250股", [{
            "placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
            "placeOrderQuantity": cell(" 34250股"),
        }])


@pytest.mark.parametrize("raw", [
    "甲证券\n买入\n2000股\n限价200\n甲账户",
    "新增指令\n标的：甲证券\n方向：买入\n数量/金额：2000股\n建仓方式：POV跟量2%，不限价\n备注：按成交量执行\n甲账户",
])
def test_one_order_multiline_fields_remain_in_the_same_scope(raw):
    row = {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("买入"),
           "placeOrderQuantity": cell("2000股"), "placeOrderShortname": cell("甲账户")}
    if "限价200" in raw:
        row["placeOrderPrice"] = cell("200", "限价200")
    else:
        row["placeOrderAlgorithmType"] = cell("POV跟量2%")
    params, _ = run(raw, [row])
    assert params.order_list[0].place_order_order_direction == "BUY"
    assert params.order_list[0].place_order_quantity == 2000


def test_unlabelled_second_instrument_line_cannot_supply_an_action():
    with pytest.raises(EvidenceError):
        run("甲证券 剩余100股持仓\n乙证券 卖出全部持仓", [{
            "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("100股"),
            "placeOrderOrderDirection": cell("卖出"), "placeOrderCloseIntent": cell("全部持仓"),
        }])


@pytest.mark.parametrize("value,expected", [("pov跟量 2%", 2), ("跟量18%", 18), ("占比10%", 10)])
def test_algorithm_participation_label_and_ratio_are_separate_fields(value, expected):
    params, _ = run("甲证券 " + value, [{"placeOrderWindCode": cell("甲证券"),
                                     "placeOrderAlgorithmType": cell(value)}])
    assert params.order_list[0].place_order_algorithm_type == "POV"
    assert params.order_list[0].place_order_pov_percent == expected


def test_buy_to_close_is_not_treated_as_opening_a_long_position():
    params, _ = run("买入平仓 甲期货 10张 不限价 POV5%", [{
        "placeOrderWindCode": cell("甲期货"), "placeOrderOrderDirection": cell("买入平仓"),
        "placeOrderQuantity": cell("10张"), "placeOrderCloseIntent": cell("买入平仓"),
    }])
    assert params.order_list[0].place_order_order_direction == "SHORT_CLOSE"
    assert params.order_list[0].place_order_close_intent is True


def test_same_instrument_and_quantity_can_use_distinct_execution_markers():
    params, _ = run("甲证券，集合竞价88.25元卖出4万股，开盘尽快卖出4万股", [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
         "placeOrderQuantity": cell("4万股"), "placeOrderPrice": cell("88.25"),
         "placeOrderPremarket": cell("集合竞价")},
        {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
         "placeOrderQuantity": cell("4万股"), "hasFastExecutionIntent": cell("尽快")},
    ])
    assert [order.place_order_quantity for order in params.order_list] == [40000, 40000]
    assert params.order_list[0].place_order_price == 88.25
    assert params.order_list[1].place_order_price is None


def test_pov_with_participation_label_is_the_same_algorithm():
    assert normalize_field("placeOrderAlgorithmType", "pov跟量") == "POV"


def test_matching_currency_suffix_can_follow_yuan_unit():
    assert normalize_field("placeOrderNotional", "1500万元 CNY") == 15000000
    with pytest.raises(ValueError, match="币种"):
        normalize_field("placeOrderNotional", "1500万元 USD")


@pytest.mark.parametrize("text", ["不要买入平仓 甲期货", "不要買入平倉 甲期货"])
def test_negated_buy_to_close_never_becomes_a_positive_close(text):
    from app.subgraphs.swap.normalize import holding_action

    assert holding_action(text) is False


def test_buy_to_close_does_not_hide_a_separate_opening_action():
    from app.subgraphs.swap.normalize import holding_action

    with pytest.raises(ValueError, match="开仓方向冲突"):
        holding_action("买入平仓甲期货，同时买入开仓甲期货")


def test_execution_markers_cannot_lend_the_first_orders_price_to_the_second():
    with pytest.raises(EvidenceError):
        run("甲证券，集合竞价88.25元卖出4万股，开盘尽快卖出4万股", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("4万股"), "placeOrderPrice": cell("88.25"),
             "placeOrderPremarket": cell("集合竞价")},
            {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("4万股"), "placeOrderPrice": cell("88.25"),
             "hasFastExecutionIntent": cell("尽快")},
        ])


@pytest.mark.parametrize("algorithm", ["pov跟量", "POV 跟量"])
def test_algorithm_label_without_ratio_does_not_invent_participation(algorithm):
    params, _ = run("甲证券 " + algorithm, [{"placeOrderWindCode": cell("甲证券"),
                                            "placeOrderAlgorithmType": cell(algorithm)}])
    order = params.order_list[0]
    assert order.place_order_algorithm_type == "POV"
    assert order.place_order_pov_percent is None
    assert order.place_order_total_pov_percent is None


@pytest.mark.parametrize("algorithm", ["ASAP", "随便跟量", "POVXYZ"])
def test_unknown_algorithm_is_not_replaced_by_pov(algorithm):
    with pytest.raises(ValueError):
        normalize_field("placeOrderAlgorithmType", algorithm)


@pytest.mark.parametrize(("raw", "amount", "code"), [
    ("1500万元 CNY", 15000000, "CNY"), ("2万港元 HKD", 20000, "HKD"),
    ("3万美元 USD", 30000, "USD"), ("￥1500万元 CNY", 15000000, "CNY"),
])
def test_matching_currency_labels_preserve_amount_and_currency(raw, amount, code):
    assert normalize_field("placeOrderNotional", raw) == amount
    assert normalize_field("placeOrderNotionalCurrency", raw) == code


@pytest.mark.parametrize("raw", ["1500万元 USD", "2万港元 CNY", "￥100 USD"])
def test_conflicting_currency_labels_are_rejected_for_both_fields(raw):
    for field in ("placeOrderNotional", "placeOrderNotionalCurrency"):
        with pytest.raises(ValueError, match="币种"):
            normalize_field(field, raw)


def test_single_leading_direction_applies_to_all_listed_orders():
    params, _ = run("卖出 甲证券100股@10 乙证券200股@20", [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
         "placeOrderQuantity": cell("100股"), "placeOrderPrice": cell("10", "@10")},
        {"placeOrderWindCode": cell("乙证券"), "placeOrderOrderDirection": cell("卖出"),
         "placeOrderQuantity": cell("200股"), "placeOrderPrice": cell("20", "@20")},
    ])
    assert [o.place_order_order_direction for o in params.order_list] == ["SELL", "SELL"]
    assert [o.place_order_price for o in params.order_list] == [10, 20]


def test_compact_orders_include_the_action_before_quantity_and_instrument():
    params, _ = run("买入100股甲证券卖出200股乙证券", [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("买入"),
         "placeOrderQuantity": cell("100股")},
        {"placeOrderWindCode": cell("乙证券"), "placeOrderOrderDirection": cell("卖出"),
         "placeOrderQuantity": cell("200股")},
    ])
    assert [o.place_order_order_direction for o in params.order_list] == ["BUY", "SELL"]
    assert [o.place_order_quantity for o in params.order_list] == [100, 200]


def test_leading_direction_does_not_override_later_explicit_direction():
    with pytest.raises(EvidenceError):
        run("卖出甲证券100股，买入乙证券200股", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("100股")},
            {"placeOrderWindCode": cell("乙证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("200股")},
        ])


def test_shared_negative_direction_is_never_promoted_to_an_order():
    with pytest.raises(ValueError):
        run("不要卖出甲证券100股乙证券200股", [
            {"placeOrderWindCode": cell("甲证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("100股")},
            {"placeOrderWindCode": cell("乙证券"), "placeOrderOrderDirection": cell("卖出"),
             "placeOrderQuantity": cell("200股")},
        ])


@pytest.mark.parametrize('text', ['不要暫買', '暂不买入', '若已買則再買', '没有已沽'])
def test_direction_modifiers_cannot_erase_negation_or_conditions(text):
    with pytest.raises(ValueError):
        normalize_field('placeOrderOrderDirection', text)


@pytest.mark.parametrize('value,context,expected', [
    ('卖出', '卖出开仓 甲期货 1张', 'SHORT_OPEN'),
    ('买入', '买入平仓 甲期货 1张', 'SHORT_CLOSE'),
])
def test_direction_fragment_retains_compound_open_close_meaning(value, context, expected):
    assert normalize_field('placeOrderOrderDirection', value, context) == expected


@pytest.mark.parametrize('text,expected', [('部分卖出', True), ('剩余全部卖出', True),
                                         ('全减', True), ('开仓', False), ('開倉', False)])
def test_explicit_close_and_open_candidate_semantics(text, expected):
    assert normalize_field('placeOrderCloseIntent', text) is expected


def test_approximate_valuation_with_precise_share_quantity_is_audited_not_ordered():
    raw = '甲证券 买入47.5万股 约2.1个亿'
    params, records = run(raw, [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('47.5万股'),
        'placeOrderOrderDirection': cell('买入'), 'placeOrderNotional': cell('约2.1个亿'),
    }])
    assert params.order_list[0].place_order_quantity == 475000
    assert params.order_list[0].place_order_notional is None
    audit = records['swap/place_order.orderList.0.placeOrderNotional']
    assert audit.value is None and audit.evidence == '约2.1个亿'


@pytest.mark.parametrize('quantity', [None, '约100股', '-100股', '100万'])
def test_approximate_order_amount_is_not_silently_made_precise(quantity):
    raw = f'甲证券 买入 {quantity or ""} 约2.1个亿'
    with pytest.raises(ValueError):
        run(raw, [{
            'placeOrderWindCode': cell('甲证券'),
            'placeOrderQuantity': cell(quantity) if quantity else None,
            'placeOrderNotional': cell('约2.1个亿'),
        }])


def test_shared_leading_action_accepts_longer_contiguous_evidence():
    raw = '沽出 甲证券100股@20 乙证券200股@30'
    params, _ = run(raw, [
        {'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
         'placeOrderOrderDirection': cell('沽出', '沽出 甲证券100股@20')},
        {'placeOrderWindCode': cell('乙证券'), 'placeOrderQuantity': cell('200股'),
         'placeOrderOrderDirection': cell('沽出', raw)},
    ])
    assert [o.place_order_order_direction for o in params.order_list] == ['SELL', 'SELL']


@pytest.mark.parametrize('raw,value', [
    ('甲证券 暫買100股', '買'), ('甲证券 已買100股', '買'),
    ('甲证券 買入了100股', '買入'), ('甲证券 已改暫買100股', '買'),
])
def test_extracting_core_direction_cannot_hide_provisional_or_completed_action(raw, value):
    from app.subgraphs.swap.errors import AmbiguousActionError

    with pytest.raises(AmbiguousActionError):
        run(raw, [{'placeOrderWindCode': cell('甲证券'),
                   'placeOrderQuantity': cell('100股'),
                   'placeOrderOrderDirection': cell(value)}])


def test_omitting_direction_does_not_turn_historical_trade_into_new_order():
    from app.subgraphs.swap.errors import AmbiguousActionError

    with pytest.raises(AmbiguousActionError):
        run('甲证券已買100股', [{'placeOrderWindCode': cell('甲证券'),
                                'placeOrderQuantity': cell('100股')}])


def test_account_name_is_not_misread_as_historical_trade_action():
    params, _ = run('买入甲证券100股 已買策略', [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('买入'), 'placeOrderShortname': cell('已買策略'),
    }])
    assert params.order_list[0].place_order_order_direction == 'BUY'


@pytest.mark.parametrize('product', ['互换', '收益互换', '场外收益互换'])
def test_derivative_product_description_is_not_a_market_selection(product):
    params, _ = run(f'{product}买入甲证券100股', [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('买入'), 'placeOrderTransactionType': cell(product),
    }])
    assert params.order_list[0].place_order_transaction_type is None
    assert params.order_list[0].place_order_order_direction == 'BUY'


def test_exchange_suffix_inside_instrument_does_not_choose_a_market():
    params, _ = run('甲证券1234.HK 买入100股', [{
        'placeOrderWindCode': cell('甲证券1234.HK'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('买入'), 'placeOrderTransactionType': cell('HK', '1234.HK'),
    }])
    assert params.order_list[0].place_order_transaction_type is None
    assert params.order_list[0].place_order_wind_code == '甲证券1234.HK'


def test_explicit_market_is_preserved_alongside_a_symbol_suffix():
    params, _ = run('深港通买入甲证券1234.HK 100股', [{
        'placeOrderWindCode': cell('甲证券1234.HK'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('买入'), 'placeOrderTransactionType': cell('深港通'),
    }])
    assert params.order_list[0].place_order_transaction_type == 'SZ_HK_CONNECT'


@pytest.mark.parametrize('scope', ['全部', '全', '一半'])
def test_bare_position_range_requires_same_order_sell_action(scope):
    params, _ = run(f'甲证券卖出100股（{scope}）', [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('卖出'), 'placeOrderCloseIntent': cell(scope),
        'placeOrderEntrustRatio': cell(scope),
    }])
    assert params.order_list[0].place_order_close_intent is True
    assert params.order_list[0].place_order_entrust_ratio == (.5 if scope == '一半' else 1)
    params, _ = run(f'甲证券100股（{scope}）', [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
        'placeOrderCloseIntent': cell(scope), 'placeOrderEntrustRatio': cell(scope),
    }])
    assert params.order_list[0].place_order_close_intent is None
    assert params.order_list[0].place_order_entrust_ratio is None


def test_short_open_with_full_size_is_not_misread_as_closing():
    params, _ = run('卖出开仓甲证券100股（全部）', [{
        'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
        'placeOrderOrderDirection': cell('卖出开仓'), 'placeOrderCloseIntent': cell('全部'),
    }])
    assert params.order_list[0].place_order_order_direction == 'SHORT_OPEN'
    assert params.order_list[0].place_order_close_intent is None


@pytest.mark.parametrize('field,value', [('placeOrderOrderDirection', '买入'), ('placeOrderPriceType', '市价')])
def test_duplicate_non_market_role_does_not_become_transaction_type(field, value):
    raw = f'甲证券 {value}100股'
    params, _ = run(raw, [{'placeOrderWindCode': cell('甲证券'), 'placeOrderQuantity': cell('100股'),
                           field: cell(value), 'placeOrderTransactionType': cell(value)}])
    assert params.order_list[0].place_order_transaction_type is None
    assert getattr(params.order_list[0], 'place_order_order_direction' if field.endswith('Direction') else 'place_order_price_type') == ('BUY' if field.endswith('Direction') else 'MarketOrder')


@pytest.mark.parametrize('wrong_field', ['placeOrderTransactionType', 'placeOrderPriceType'])
def test_auction_evidence_belongs_to_premarket_requirement(wrong_field):
    raw = '甲证券 集合竞价27.69元卖出100股'
    params, records = run(raw, [{'placeOrderWindCode': cell('甲证券'),
                                'placeOrderQuantity': cell('100股'),
                                'placeOrderOrderDirection': cell('卖出'),
                                'placeOrderPrice': cell('27.69元'),
                                wrong_field: cell('集合竞价', raw)}])
    order = params.order_list[0]
    assert order.place_order_premarket is True
    assert order.place_order_price_type == 'LimitOrder'
    assert order.place_order_transaction_type is None
    assert records['swap/place_order.orderList.0.placeOrderPremarket'].evidence == raw


def test_market_role_correction_does_not_invent_direction():
    with pytest.raises(ValueError):
        run('甲证券买入100股', [{'placeOrderWindCode': cell('甲证券'),
                            'placeOrderQuantity': cell('100股'), 'placeOrderTransactionType': cell('买入')}])


def test_action_word_inside_instrument_name_is_not_a_trade_direction():
    with pytest.raises(ValueError):
        run('买入科技100股', [{'placeOrderWindCode': cell('买入科技'),
                            'placeOrderQuantity': cell('100股'), 'placeOrderOrderDirection': cell('买入'),
                            'placeOrderTransactionType': cell('买入')}])


def test_conflicting_direction_cannot_be_hidden_as_duplicate_market():
    with pytest.raises(ValueError):
        run('甲证券买入或卖出100股', [{'placeOrderWindCode': cell('甲证券'),
                             'placeOrderQuantity': cell('100股'), 'placeOrderOrderDirection': cell('卖出'),
                             'placeOrderTransactionType': cell('买入')}])


@pytest.mark.parametrize('raw,expected', [('不要集合竞价', False), ('不要在盘前下单', False),
                                         ('不要市价，集合竞价卖出', True)])
def test_premarket_negation_stays_attached_to_its_own_requirement(raw, expected):
    value = '集合竞价' if '集合竞价' in raw else '盘前'
    assert normalize_field('placeOrderPremarket', value, raw) is expected


@pytest.mark.parametrize('raw', ['如果盘前就执行', '盘前或盘中', '不要盘前，改集合竞价'])
def test_premarket_conditions_and_conflicts_are_not_assumed(raw):
    with pytest.raises(ValueError):
        normalize_field('placeOrderPremarket', '盘前', raw)


def test_duplicate_market_correction_does_not_erase_negated_price_type():
    with pytest.raises(ValueError):
        run('甲证券不要按市价买入100股', [{'placeOrderWindCode': cell('甲证券'),
            'placeOrderQuantity': cell('100股'), 'placeOrderOrderDirection': cell('买入'),
            'placeOrderPriceType': cell('市价'), 'placeOrderTransactionType': cell('市价')}])


def test_duplicate_market_correction_does_not_erase_wait_condition():
    with pytest.raises(ValueError):
        run('甲证券买入100股，等通知再执行', [{'placeOrderWindCode': cell('甲证券'),
            'placeOrderQuantity': cell('100股'), 'placeOrderOrderDirection': cell('买入'),
            'placeOrderTransactionType': cell('买入')}])


@pytest.mark.parametrize('wrong', ['买入', '互换', 'HK', '集合竞价'])
def test_role_correction_cannot_erase_explicit_market_restriction(wrong):
    raw = f'港股 互换 买入甲证券1234.HK 100股 集合竞价'
    with pytest.raises(ValueError):
        run(raw, [{'placeOrderWindCode': cell('甲证券1234.HK'),
                   'placeOrderQuantity': cell('100股'), 'placeOrderOrderDirection': cell('买入'),
                   'placeOrderPremarket': cell('集合竞价'),
                   'placeOrderTransactionType': cell(wrong)}])
