"""真实失败候选与执行方式边界；仅运行纯归一化及隔离子图。"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.observability.diagnostics import failure_diagnostic
from app.subgraphs.close import place_close as pc
from app.subgraphs.close.normalization import normalize_place_candidates
from app.subgraphs.close.reference_parser import parse_reference_message
from tests.subgraphs.close.candidate_fixtures import close_candidates
from tests.subgraphs.close.test_candidate_migration import mock_close as _mock_close

ORDER = "CO-20260921-ABCDEF12"
SECOND = "CO-20260921-ABCDEF34"
CONTRACT = "OPTG-TEST20260009"


def mock_close(monkeypatch, rows, holdings=()):
    return _mock_close(
        monkeypatch, close_candidates(*rows).model_dump()["closeOrderList"], holdings
    )


def normalize(raw, *rows, quote="", data=()):
    return normalize_place_candidates(
        close_candidates(*rows),
        {"raw": raw, "quote": quote},
        parse_reference_message(quote, raw),
        list(data),
    )


async def test_trace_4590e34d_original_candidate_reaches_submission(monkeypatch):
    # 与真实 Trace 相同的候选值与证据；替换持仓身份以免提交真实业务数据。
    raw = "序号12 100w 市价下单"
    quote = f"序号：12\n单号：{ORDER}\n合约编号：{CONTRACT}"
    rows = [{"orderId": "序号12", "closeOrderNotionalDelta": "100w", "closeOrderType": "市价下单"}]
    _, model, submit = mock_close(monkeypatch, rows, [{"orderId": ORDER, "contractCode": CONTRACT}])
    result = await pc.close_place_close({"raw_text": raw, "quote_content": quote})
    assert result.get("error") is None, result.get("error")
    sent = submit.await_args.kwargs["close_order_req_vo"]["closeOrderList"]
    assert len(sent) == 1
    assert (
        sent[0]["orderId"],
        sent[0]["internalTradeId"],
        sent[0]["closeOrderNotionalDelta"],
        sent[0]["closeOrderType"],
    ) == (ORDER, CONTRACT, "1000000", "市价单")
    record = result["field_records"]["close/place_close.orderList.0.closeOrderType"]
    assert record.value == "市价单" and record.evidence == "市价下单" and record.locked
    assert model.with_structured_output.return_value.ainvoke.await_count == 1
    assert submit.await_count == 1


@pytest.mark.parametrize(
    "text,expected",
    [
        ("市价下单", "市价单"),
        ("市价平仓", "市价单"),
        ("以市价平仓", "市价单"),
        ("使用市价单委托", "市价单"),
        ("采用 MARKET 执行", "市价单"),
        ("限价下单", "限价单"),
        ("按限价平仓", "限价单"),
        ("用LMT委托", "限价单"),
        ("按POV执行", "POV"),
        ("采用跟量平仓", "POV"),
        ("最大跟量下单", None),
        ("按TWAP平仓", "TWAP"),
        ("用时间加权执行", "TWAP"),
        ("按 ＰＯＶ 执行", "POV"),
        ("  按 市价 下单  ", "市价单"),
        ("按市价进行平仓", "市价单"),
        ("市价", "市价单"),
        ("市价单", "市价单"),
        ("market", "市价单"),
        ("mkt", "市价单"),
        ("限价", "限价单"),
        ("limit", "限价单"),
        ("正常挂单", "POV"),
        ("拉满跟量", None),
        ("全跟量", None),
        ("均匀执行", "TWAP"),
        ("不用跟量", "市价单"),
        ("不跟量", "市价单"),
        ("不要跟量", "市价单"),
    ],
)
def test_explicit_execution_phrases(text, expected):
    result, _ = normalize(f"{ORDER} {text}", {"orderId": ORDER, "closeOrderType": text})
    assert result.close_order_list[0].close_order_type == expected


@pytest.mark.parametrize(
    "raw,candidate",
    [
        ("不要市价下单", "市价"),
        ("不要按市价平仓", "市价"),
        ("不要走市价下单", "市价"),
        ("到10再市价下单", "市价"),
        ("not market", "market"),
        ("if ready then mkt", "mkt"),
        ("market or you choose", "market"),
        ("不使用限价下单", "限价"),
        ("市价平仓吗", "市价"),
        ("如果能成交就市价下单", "市价"),
        ("先限价10，不行就市价", "限价"),
        ("市价或限价都可以", "市价"),
        ("市价限价", "市价"),
        ("POV与TWAP都可以", "POV"),
        ("POV TWAP", "POV"),
        ("市价或者你决定", "市价"),
        ("不知道怎么平", "不知道怎么平"),
        ("超市价格下单", "超市价格下单"),
        ("冰山", "冰山"),
    ],
)
async def test_unsafe_or_unknown_type_stops_before_submit(monkeypatch, raw, candidate):
    _, _, submit = mock_close(monkeypatch, [{"orderId": ORDER, "closeOrderType": candidate}])
    result = await pc.close_place_close({"raw_text": f"{ORDER} {raw}"})
    submit.assert_not_awaited()
    error = result["error"]
    assert error.node == "place_close_normalize" and error.code == "E3"
    assert error.type == "CloseOrderTypeNormalizationError"
    assert "closeOrderType" in error.message and candidate in error.message
    diagnostic = failure_diagnostic(result)
    assert diagnostic["summary"] == "平仓执行方式无法识别或存在冲突"
    assert "place_close_submit" not in [t.node for t in result["trace"]]


async def test_invalid_omitted_type_cannot_fall_through_to_price_inference(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"orderId": ORDER, "closeOrderPrice": "10"}])
    result = await pc.close_place_close({"raw_text": f"{ORDER} 不要市价，价格10"})
    submit.assert_not_awaited()
    assert result["error"].type == "CloseOrderTypeNormalizationError"


@pytest.mark.parametrize(
    "algorithm,extras",
    [
        ("POV", {"closeOrderPovRatio": "25%"}),
        ("TWAP", {"closeOrderAlgoStartTime": "9:30", "closeOrderAlgoEndTime": "14:00"}),
    ],
)
def test_algorithm_with_limit_preserves_independent_fields(algorithm, extras):
    raw = f"{ORDER} 按{algorithm}执行，限价10，" + "-".join(extras.values())
    candidate = {
        "orderId": ORDER,
        "closeOrderType": f"按{algorithm}执行",
        "closeOrderPrice": "10",
        **extras,
    }
    result, _ = normalize(raw, candidate)
    row = result.close_order_list[0]
    assert row.close_order_type == algorithm and row.close_order_price == 10
    if algorithm == "POV":
        assert row.close_order_pov_ratio == 25
    else:
        assert (row.close_order_algo_start_time, row.close_order_algo_end_time) == (
            "09:30",
            "14:00",
        )


def test_no_follow_compatibility_and_max_follow_intent_remain():
    for phrase, expected, fast in [("不用跟量", "市价单", None), ("最大跟量下单", None, True)]:
        result, _ = normalize(
            f"{ORDER} {phrase}，正常挂单", {"orderId": ORDER, "closeOrderType": phrase}
        )
        assert result.close_order_list[0].close_order_type == expected
        assert result.close_order_list[0].close_order_pov_ratio is None
        assert result.close_order_list[0].has_fast_execution_intent is fast


def test_multi_order_type_and_evidence_are_isolated():
    rows = [
        {"orderId": ORDER, "closeOrderType": "市价下单"},
        {"orderId": SECOND, "closeOrderType": "按限价平仓", "closeOrderPrice": "10"},
    ]
    before = deepcopy(rows)
    params, records = normalize(f"{ORDER} 市价下单；{SECOND} 按限价平仓，价格10", *rows)
    assert [r.close_order_type for r in params.close_order_list] == ["市价单", "限价单"]
    assert records["close/place_close.orderList.0.closeOrderType"].evidence == "市价下单"
    assert records["close/place_close.orderList.1.closeOrderType"].evidence == "按限价平仓"
    assert rows == before


def test_negation_on_other_order_does_not_change_selected_order():
    result, _ = normalize(
        f"{ORDER} 市价下单；{SECOND} 不要市价下单", {"orderId": ORDER, "closeOrderType": "市价下单"}
    )
    assert (
        len(result.close_order_list) == 1
        and result.close_order_list[0].close_order_type == "市价单"
    )


async def test_negation_before_target_is_not_dropped(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"orderId": ORDER, "closeOrderType": "市价"}])
    result = await pc.close_place_close({"raw_text": f"不要对 {ORDER} 市价下单"})
    submit.assert_not_awaited()
    assert result["error"].type == "CloseOrderTypeNormalizationError"


def test_leading_negation_on_first_target_does_not_leak_to_second():
    result, _ = normalize(
        f"不要对 {ORDER} 市价下单；{SECOND} 限价下单",
        {"orderId": SECOND, "closeOrderType": "限价下单"},
    )
    assert result.close_order_list[0].order_id == SECOND
    assert result.close_order_list[0].close_order_type == "限价单"


@pytest.mark.parametrize("masked_field", ["closeOrderType", "value"])
def test_error_candidate_respects_configured_masking(monkeypatch, masked_field):
    from types import SimpleNamespace

    from app.observability import privacy

    monkeypatch.setattr(
        privacy,
        "get_settings",
        lambda: SimpleNamespace(
            telemetry_masking_enabled=True,
            telemetry_masking_fields=masked_field,
        ),
    )
    with pytest.raises(ValueError) as error:
        normalize(f"{ORDER} 私有未知方式", {"orderId": ORDER, "closeOrderType": "私有未知方式"})
    assert "私有未知方式" not in str(error.value) and "[redacted]" in str(error.value)


def test_public_diagnostic_does_not_expose_candidate():
    from app.api.routes import _state_to_outputs
    from app.graph.state import ErrorInfo

    error = ErrorInfo(
        node="place_close_normalize",
        type="CloseOrderTypeNormalizationError",
        message="private candidate",
    )
    output = _state_to_outputs({"error": error})
    assert output["diagnostic"]["code"] == "E3"
    assert output["diagnostic"]["summary"] == "平仓执行方式无法识别或存在冲突"
    assert "private candidate" not in str(output)


def test_contract_name_is_not_execution_type_evidence():
    with pytest.raises(ValueError, match="closeOrderType"):
        normalize(
            "OPT-MARKET 平100万", {"internalTradeId": "OPT-MARKET", "closeOrderType": "MARKET"}
        )


@pytest.mark.parametrize(
    "extras,expected",
    [
        ({"closeOrderPrice": "10"}, "限价单"),
        ({"closeOrderPovRatio": "15%"}, "POV"),
        ({"closeOrderAlgoStartTime": "09:30"}, "TWAP"),
    ],
)
def test_absent_type_keeps_existing_inference(extras, expected):
    result, _ = normalize(f"{ORDER} " + " ".join(extras.values()), {"orderId": ORDER, **extras})
    assert result.close_order_list[0].close_order_type == expected


@pytest.mark.parametrize("candidate", ["跟量", "正常挂单"])
async def test_cropped_no_follow_cannot_enable_pov(monkeypatch, candidate):
    _, _, submit = mock_close(monkeypatch, [{"orderId": ORDER, "closeOrderType": candidate}])
    result = await pc.close_place_close({"raw_text": f"{ORDER} 不用跟量，正常挂单"})
    submit.assert_not_awaited()
    assert result["error"].type == "CloseOrderTypeNormalizationError"
    assert "reason=negated" in result["error"].message


def test_market_followed_by_no_follow_is_not_negated_market():
    result, _ = normalize(f"{ORDER} 市价不要跟量", {"orderId": ORDER, "closeOrderType": "市价"})
    assert result.close_order_list[0].close_order_type == "市价单"


@pytest.mark.parametrize(
    "text,extras",
    [
        ("不用跟量 15%", {"closeOrderPovRatio": "15%"}),
        ("市价下单 价格10", {"closeOrderPrice": "10"}),
    ],
)
async def test_inference_cannot_contradict_explicit_order_text(monkeypatch, text, extras):
    _, _, submit = mock_close(monkeypatch, [{"orderId": ORDER, **extras}])
    result = await pc.close_place_close({"raw_text": f"{ORDER} {text}"})
    submit.assert_not_awaited()
    assert result["error"].type == "CloseOrderTypeNormalizationError"
