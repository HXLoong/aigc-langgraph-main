"""OptionOrderItem / OptionOrderItemWithFastExec 共享 schema 测试（Dify DSL v2）。

7 个 extract 节点共用 13 字段 orderList item schema；`place_order_from_quote`
（下单）额外多 hasFastExecutionIntent 字段。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.subgraphs.option.models import (
    OptionOrderItem,
    OptionOrderItemWithFastExec,
)


class TestOptionOrderItem:
    def test_minimal_with_only_order_id(self) -> None:
        item = OptionOrderItem(orderId="Q-20250616-000011")
        assert item.order_id == "Q-20250616-000011"
        assert item.order_type is None

    def test_all_fields(self) -> None:
        item = OptionOrderItem(
            orderId="Q-1",
            stockCode="600519.SH",
            optionType="欧式看涨",
            tenor="1M",
            strikePercentage=100.0,
            notionalAmount="1000000",
            participationRate=90.0,
            orderType="POV",
            limitPrice=9.1,
            povRatio=25.0,
            twapStartTime="09:30",
            twapEndTime="15:00",
            shortName="11125测试短名（张天琪专用）",
        )
        assert item.stock_code == "600519.SH"
        assert item.twap_start_time == "09:30"
        assert item.twap_end_time == "15:00"
        assert item.short_name == "11125测试短名（张天琪专用）"

    def test_option_type_restricted_to_three_values(self) -> None:
        """Dify DSL v2 收窄：optionType 只接受 3 个值，不再支持 欧式看跌/气囊。"""
        for valid in ("欧式看涨", "参与型看涨", "雪球"):
            assert OptionOrderItem(optionType=valid).option_type == valid  # type: ignore[arg-type]
        for removed in ("欧式看跌", "气囊"):
            with pytest.raises(ValidationError):
                OptionOrderItem(optionType=removed)  # type: ignore[arg-type]

    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OptionOrderItem(orderId="Q-1", orderType="冰山单")  # type: ignore[arg-type]

    def test_order_id_optional(self) -> None:
        item = OptionOrderItem.model_validate({})
        assert item.order_id is None

    def test_extra_fields_ignored(self) -> None:
        params = OptionOrderItem.model_validate({"orderId": "Q-1", "garbage": "x"})
        assert params.order_id == "Q-1"


class TestOptionOrderItemWithFastExec:
    def test_inherits_base_fields(self) -> None:
        item = OptionOrderItemWithFastExec(orderId="Q-1", orderType="市价单")
        assert item.order_id == "Q-1"
        assert item.order_type == "市价单"

    def test_has_fast_execution_intent_field(self) -> None:
        item = OptionOrderItemWithFastExec(hasFastExecutionIntent=True)
        assert item.has_fast_execution_intent is True

    def test_default_none(self) -> None:
        item = OptionOrderItemWithFastExec()
        assert item.has_fast_execution_intent is None
