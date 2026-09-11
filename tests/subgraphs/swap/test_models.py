"""swap 子图 Pydantic 模型测试。

覆盖 `app/subgraphs/swap/models.py`：
- `SwapIntentOutput` / `SwapIntentType`：7 个合法意图
- `SwapOrderItem` / `SwapPlaceOrderParams`：下单参数（含 DSL v2 新增枚举）
- `SwapOrderRefItem` / `SwapConfirmParams` / `SwapCancelParams` / `SwapQueryParams`
- `SwapTickerPick` / `SwapSelectTickerOutput`（互换-选择标的指针）
- `SwapCounterpartyPick` / `SwapSelectCounterpartyOutput`（互换-选择交易对手指针）

测试方法：G4 模型校验（合法/非法值 + `extra="ignore"` 语义）。
"""
from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.subgraphs.swap.models import (
    SwapCancelParams,
    SwapConfirmParams,
    SwapCounterpartyPick,
    SwapIntentOutput,
    SwapIntentType,
    SwapOrderItem,
    SwapOrderRefItem,
    SwapPlaceOrderParams,
    SwapQueryParams,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
    SwapTickerPick,
)

# ============================================================
# SwapIntentType / SwapIntentOutput
# ============================================================


class TestSwapIntentOutput:
    @pytest.mark.parametrize(
        "intent_type",
        [
            "place_order_request",
            "cancel_order_request",
            "confirm_order",
            "confirm_cancel_order",
            "confirm_modify_order",
            "query_order_status",
            "unknown_intent",
        ],
    )
    def test_all_seven_intent_types_accepted(self, intent_type: str) -> None:
        obj = SwapIntentOutput(type=intent_type)  # type: ignore[arg-type]
        assert obj.type == intent_type

    def test_literal_has_exactly_seven_values(self) -> None:
        """对齐 Java SwapIntentionType 7 值（CONTEXT.md / ADR 0001 D2）。"""
        assert len(get_args(SwapIntentType)) == 7

    def test_invalid_intent_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapIntentOutput(type="not_a_real_intent")  # type: ignore[arg-type]

    def test_option_intent_names_rejected(self) -> None:
        """期权枚举（new_inquiry / request_cancel_order）不能混入 swap。"""
        for name in ("new_inquiry", "request_cancel_order", "request_modify_order"):
            with pytest.raises(ValidationError):
                SwapIntentOutput(type=name)  # type: ignore[arg-type]

    def test_extra_fields_ignored(self) -> None:
        """LLM 输出多字段时静默忽略（qwen-max 经常输出额外字段）。"""
        params = SwapIntentOutput.model_validate(
            {"type": "place_order_request", "extra_garbage": "x"}
        )
        assert params.type == "place_order_request"

    def test_missing_type_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            SwapIntentOutput.model_validate({})


# ============================================================
# SwapOrderItem / SwapPlaceOrderParams
# ============================================================


class TestSwapOrderItem:
    def test_minimal_all_none(self) -> None:
        item = SwapOrderItem()
        assert item.order_id is None
        assert item.place_order_wind_code is None
        assert item.place_order_quantity is None

    def test_full_buy_order(self) -> None:
        item = SwapOrderItem(
            placeOrderWindCode="0700.HK",
            placeOrderTransactionType="HK_STOCK",
            placeOrderQuantity=1000,
            placeOrderOrderDirection="BUY",
            placeOrderPriceType="LimitOrder",
            placeOrderAlgorithmType="POV",
            placeOrderPrice=320,
            placeOrderPovPercent=25,
            placeOrderShortname="ACCOUNT_L",
        )
        assert item.place_order_transaction_type == "HK_STOCK"
        assert item.place_order_order_direction == "BUY"
        assert item.place_order_algorithm_type == "POV"

    def test_modify_order_with_order_id(self) -> None:
        item = SwapOrderItem(orderId="H-20260304-0001", placeOrderPrice=350)
        assert item.order_id == "H-20260304-0001"

    def test_dsl_v2_new_fields(self) -> None:
        item = SwapOrderItem(
            placeOrderQuantity=100,
            placeOrderQuantityUnit="HAND",
            placeOrderNotional=200000,
            placeOrderNotionalCurrency="CNY",
            placeOrderEntrustRatio=0.5,
            placeOrderRelativeTimeMinutes=30,
            placeOrderCloseIntent=True,
            hasFastExecutionIntent=False,
        )
        assert item.place_order_quantity_unit == "HAND"
        assert item.place_order_notional_currency == "CNY"
        assert item.place_order_relative_time_minutes == 30
        assert item.place_order_close_intent is True
        assert item.has_fast_execution_intent is False

    @pytest.mark.parametrize(
        "tx_type",
        [
            "A_SHARE",
            "HK_STOCK",
            "US_STOCK",
            "SZ_HK_CONNECT",
            "SH_HK_CONNECT",
            "CHN_FUTURE",
            "CROSS_FUTURE",
            "FUTURES",
            "FUND",
            "INDEX",
            "BOND",
            "OTHERS",
        ],
    )
    def test_all_transaction_types(self, tx_type: str) -> None:
        item = SwapOrderItem(placeOrderTransactionType=tx_type)  # type: ignore[arg-type]
        assert item.place_order_transaction_type == tx_type

    def test_invalid_transaction_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderTransactionType="CRYPTO")  # type: ignore[arg-type]

    @pytest.mark.parametrize("direction", ["BUY", "SELL", "SHORT_OPEN", "SHORT_CLOSE"])
    def test_all_order_directions(self, direction: str) -> None:
        """4 值对齐 Java GoatsOrderDirection（swap-023 卖空回归保护）。"""
        item = SwapOrderItem(placeOrderOrderDirection=direction)  # type: ignore[arg-type]
        assert item.place_order_order_direction == direction

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderOrderDirection="HOLD")  # type: ignore[arg-type]

    @pytest.mark.parametrize("price_type", ["LimitOrder", "MarketOrder"])
    def test_all_price_types(self, price_type: str) -> None:
        item = SwapOrderItem(placeOrderPriceType=price_type)  # type: ignore[arg-type]
        assert item.place_order_price_type == price_type

    def test_invalid_price_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderPriceType="StopLoss")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "algo", ["POV", "TWAP", "VWAP", "ICEBERG", "SNIPER"]
    )
    def test_all_algorithm_types(self, algo: str) -> None:
        item = SwapOrderItem(placeOrderAlgorithmType=algo)  # type: ignore[arg-type]
        assert item.place_order_algorithm_type == algo

    def test_invalid_algorithm_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderAlgorithmType="ALGO")  # type: ignore[arg-type]

    @pytest.mark.parametrize("unit", ["HAND", "SHARE", "AMOUNT"])
    def test_all_quantity_units(self, unit: str) -> None:
        item = SwapOrderItem(placeOrderQuantityUnit=unit)  # type: ignore[arg-type]
        assert item.place_order_quantity_unit == unit

    def test_invalid_quantity_unit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderQuantityUnit="LOT")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "currency",
        ["CNY", "USD", "HKD", "EUR", "GBP", "JPY", "AUD", "NZD", "CNH"],
    )
    def test_all_notional_currencies(self, currency: str) -> None:
        item = SwapOrderItem(placeOrderNotionalCurrency=currency)  # type: ignore[arg-type]
        assert item.place_order_notional_currency == currency

    def test_invalid_currency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderNotionalCurrency="BTC")  # type: ignore[arg-type]

    def test_extra_fields_ignored(self) -> None:
        """extra='ignore' 让 LLM 输出多字段不触发 ValidationError。"""
        item = SwapOrderItem.model_validate({"orderId": None, "garbage_field": "x"})
        assert item.order_id is None

    def test_legacy_quantity_hand_still_accepted(self) -> None:
        """旧字段 placeOrderQuantityHand 保留（render.py 仍读取）。"""
        item = SwapOrderItem(placeOrderQuantityHand=5)
        assert item.place_order_quantity_hand == 5


class TestSwapPlaceOrderParams:
    def test_default_empty_list(self) -> None:
        assert SwapPlaceOrderParams().order_list == []

    def test_accepts_top_level_type_field(self) -> None:
        """LLM 输出的顶层 'type' 字段被 ignore。"""
        p = SwapPlaceOrderParams.model_validate(
            {"type": "place_order_request", "orderList": []}
        )
        assert p.order_list == []

    def test_parses_nested_order_items(self) -> None:
        p = SwapPlaceOrderParams.model_validate(
            {"orderList": [{"placeOrderWindCode": "600519.SH", "placeOrderQuantity": 100}]}
        )
        assert isinstance(p.order_list[0], SwapOrderItem)
        assert p.order_list[0].place_order_quantity == 100

    def test_multiple_orders(self) -> None:
        p = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(placeOrderWindCode="600519.SH"),
                SwapOrderItem(placeOrderWindCode="00700.HK"),
            ]
        )
        assert len(p.order_list) == 2


# ============================================================
# 确认 / 撤单 / 查询 共享 schema
# ============================================================


class TestOrderRefSchemas:
    def test_order_ref_item_allows_null_order_id(self) -> None:
        assert SwapOrderRefItem().order_id is None

    def test_confirm_params_default_empty(self) -> None:
        assert SwapConfirmParams().order_list == []

    def test_cancel_params_default_empty(self) -> None:
        assert SwapCancelParams().order_list == []

    def test_query_params_default_empty(self) -> None:
        assert SwapQueryParams().order_list == []

    def test_confirm_params_parses_order_ids(self) -> None:
        p = SwapConfirmParams.model_validate(
            {"orderList": [{"orderId": "H-1"}, {"orderId": None}]}
        )
        assert [i.order_id for i in p.order_list] == ["H-1", None]

    def test_extra_fields_ignored(self) -> None:
        p = SwapCancelParams.model_validate({"orderList": [], "operate": "交易"})
        assert p.order_list == []


# ============================================================
# 选择标的 / 选择交易对手 指针
# ============================================================


class TestSelectTickerModels:
    def test_pick_defaults_all_none(self) -> None:
        pick = SwapTickerPick()
        assert pick.order_id is None
        assert pick.order_seq is None
        assert pick.idx is None
        assert pick.seq is None
        assert pick.direct_ref is None

    def test_output_default_empty_picks(self) -> None:
        assert SwapSelectTickerOutput().picks == []

    def test_output_parses_picks(self) -> None:
        out = SwapSelectTickerOutput.model_validate(
            {"picks": [{"orderId": "H-1", "seq": 2}, {"orderId": "H-2", "directRef": "腾讯"}]}
        )
        assert [p.seq for p in out.picks] == [2, None]
        assert out.picks[1].direct_ref == "腾讯"

    def test_extra_fields_ignored(self) -> None:
        out = SwapSelectTickerOutput.model_validate({"picks": [], "garbage": 1})
        assert out.picks == []


class TestSelectCounterpartyModels:
    def test_pick_defaults_all_none(self) -> None:
        pick = SwapCounterpartyPick()
        assert pick.letter is None
        assert pick.ordinal is None
        assert pick.direct_name is None

    def test_output_has_signal_defaults_false(self) -> None:
        out = SwapSelectCounterpartyOutput()
        assert out.has_signal is False
        assert out.picks == []

    def test_output_parses_letter_and_ordinal(self) -> None:
        out = SwapSelectCounterpartyOutput.model_validate(
            {
                "hasSignal": True,
                "picks": [
                    {"orderId": "H-1", "letter": "B"},
                    {"orderId": "H-2", "ordinal": 3},
                    {"orderId": "H-3", "directName": "临沂阿凡提"},
                ],
            }
        )
        assert out.has_signal is True
        assert out.picks[0].letter == "B"
        assert out.picks[1].ordinal == 3
        assert out.picks[2].direct_name == "临沂阿凡提"

    def test_extra_fields_ignored(self) -> None:
        out = SwapSelectCounterpartyOutput.model_validate(
            {"hasSignal": True, "picks": [], "garbage": 1}
        )
        assert out.picks == []
