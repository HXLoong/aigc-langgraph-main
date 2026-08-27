"""#160 裁决落地：AgentState 业务参数写入边界校验（ADR 0001 D6）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.graph.business_params import (
    validated_cancel_params,
    validated_close_params,
    validated_confirm,
    validated_place_params,
    validated_query_filter,
)


class TestOutputByteIdentical:
    """输出必须与历史直接写 dict 的形状逐字节一致（只含调用方提供的键）。"""

    def test_swap_place(self) -> None:
        out = validated_place_params(expected_action="place", orderList=[{"orderId": "H-1"}])
        assert out == {"expected_action": "place", "orderList": [{"orderId": "H-1"}]}

    def test_option_inquiry_empty_orderlist(self) -> None:
        out = validated_place_params(expected_action="inquiry", orderList=[])
        assert out == {"expected_action": "inquiry", "orderList": []}

    def test_swap_cancel_only_orderlist(self) -> None:
        assert validated_cancel_params(orderList=[{"a": 1}]) == {"orderList": [{"a": 1}]}

    def test_close_cancel_orderno_list(self) -> None:
        out = validated_cancel_params(cancelOrderNoList=["CO-1"])
        assert out == {"cancelOrderNoList": ["CO-1"]}

    def test_close_confirm(self) -> None:
        out = validated_confirm(action="close", confirmOrderNoList=["CO-2"])
        assert out == {"action": "close", "confirmOrderNoList": ["CO-2"]}

    def test_query_filter_variants(self) -> None:
        assert validated_query_filter(orderList=[]) == {"orderList": []}
        assert validated_query_filter(queryOrderNoList=["Q-1"]) == {"queryOrderNoList": ["Q-1"]}

    def test_close_params_passthrough(self) -> None:
        kw = {"windCode": "600519.SH", "direction": "long", "quantity": 100}
        assert validated_close_params(**kw) == kw


class TestValidationFailsFast:
    def test_typo_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validated_place_params(expected_acton="place", orderList=[])  # 拼错字段名

    def test_wrong_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validated_place_params(expected_action="place", orderList="not-a-list")

    def test_confirm_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validated_confirm(action="close", confirmOrderNos=["x"])


class TestWritersUseValidation:
    """全部信封写入点必须走 business_params（静态防回退）。"""

    def test_writer_modules_import_helpers(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        writers = {
            "app/subgraphs/swap/place_order.py": "validated_place_params",
            "app/subgraphs/swap/cancel.py": "validated_cancel_params",
            "app/subgraphs/swap/confirm.py": "validated_confirm",
            "app/subgraphs/swap/query_order.py": "validated_query_filter",
            "app/subgraphs/option/extract_inquiry.py": "validated_place_params",
            "app/subgraphs/option/extract_place.py": "validated_place_params",
            "app/subgraphs/option/extract_confirm_place.py": "validated_confirm",
            "app/subgraphs/option/extract_cancel_place.py": "validated_cancel_params",
            "app/subgraphs/option/extract_cancel.py": "validated_cancel_params",
            "app/subgraphs/option/extract_confirm_cancel.py": "validated_confirm",
            "app/subgraphs/option/extract_query.py": "validated_query_filter",
            "app/subgraphs/close/cancel_close.py": "validated_cancel_params",
            "app/subgraphs/close/confirm_close.py": "validated_confirm",
            "app/subgraphs/close/confirm_cancel.py": "validated_confirm",
            "app/subgraphs/close/query_status.py": "validated_query_filter",
            "app/subgraphs/close/holding_query.py": "validated_close_params",
            "app/subgraphs/close/place_close.py": "validated_close_params",
        }
        missing = [
            f for f, helper in writers.items()
            if helper not in (root / f).read_text(encoding="utf-8")
        ]
        assert missing == [], f"以下写入点未走 business_params 校验: {missing}"
