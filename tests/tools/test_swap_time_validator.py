"""SwapOrderOpenApiBaseSaveReqVO 时间字段兼容性测试。

Round 9 eval 暴露：swap.place_order LLM 输出"14:00"/"15:00"作为算法窗口起止时间，
但 SwapOrderOpenApiBaseSaveReqVO.placeOrderStartTime 字段类型是 datetime，pydantic
拒绝"14:00"（"input is too short"）→ ValidationError → 节点抛错 → 后端调用失败。

修复：给 placeOrderStartTime/placeOrderEndTime 加 field validator，能把
"HH:MM" / "HH:MM:SS" 短时间字符串自动补齐为今天的 datetime。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.tools.swap_client import SwapOrderOpenApiBaseSaveReqVO


class TestSwapTimeValidator:
    """LLM 短时间字符串 → 自动 promote 为 datetime。"""

    def test_hh_mm_promoted_to_today_datetime(self) -> None:
        """`14:00` → 今天 14:00:00。"""
        item = SwapOrderOpenApiBaseSaveReqVO(
            placeOrderStartTime="14:00",  # type: ignore[arg-type]
            placeOrderEndTime="15:00",  # type: ignore[arg-type]
        )
        assert isinstance(item.place_order_start_time, datetime)
        assert isinstance(item.place_order_end_time, datetime)
        assert item.place_order_start_time.hour == 14
        assert item.place_order_start_time.minute == 0
        assert item.place_order_end_time.hour == 15
        # 日期应该是今天
        assert item.place_order_start_time.date() == datetime.now().date()

    def test_hh_mm_ss_also_works(self) -> None:
        """`14:30:45` 三段时间也能解析。"""
        item = SwapOrderOpenApiBaseSaveReqVO(
            placeOrderStartTime="14:30:45",  # type: ignore[arg-type]
        )
        assert item.place_order_start_time.hour == 14
        assert item.place_order_start_time.minute == 30
        assert item.place_order_start_time.second == 45

    def test_full_iso_datetime_unchanged(self) -> None:
        """完整 ISO datetime 字符串仍走 pydantic 默认解析，结果一致。"""
        item = SwapOrderOpenApiBaseSaveReqVO(
            placeOrderStartTime="2026-05-14T09:30:00",  # type: ignore[arg-type]
        )
        assert item.place_order_start_time.year == 2026
        assert item.place_order_start_time.month == 5
        assert item.place_order_start_time.day == 14
        assert item.place_order_start_time.hour == 9

    def test_datetime_object_unchanged(self) -> None:
        """直接传 datetime 对象保持不变。"""
        dt = datetime(2026, 5, 14, 10, 0)
        item = SwapOrderOpenApiBaseSaveReqVO(placeOrderStartTime=dt)
        assert item.place_order_start_time == dt

    def test_none_value_allowed(self) -> None:
        """None 是合法值。"""
        item = SwapOrderOpenApiBaseSaveReqVO(placeOrderStartTime=None)
        assert item.place_order_start_time is None

    def test_invalid_string_raises(self) -> None:
        """非时间字符串依然拒绝。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SwapOrderOpenApiBaseSaveReqVO(placeOrderStartTime="not-a-time")  # type: ignore[arg-type]
