"""SwapOrderOpenApiBaseSaveReqVO 时间字段兼容性测试。

Round 9 eval 暴露：swap.place_order LLM 输出"14:00"/"15:00"作为算法窗口起止时间，
但 SwapOrderOpenApiBaseSaveReqVO.placeOrderStartTime 字段类型是 datetime，pydantic
拒绝"14:00"（"input is too short"）→ ValidationError → 节点抛错 → 后端调用失败。

修复：给 placeOrderStartTime/placeOrderEndTime 加 field validator，能把
"HH:MM" / "HH:MM:SS" 短时间字符串自动补齐为今天的 datetime。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.tools.swap_client import (
    SwapClientHttpx,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)


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


@pytest.mark.parametrize("field", ["placeOrderStartTime", "placeOrderEndTime"])
@pytest.mark.parametrize(
    "value",
    [
        "2026-09-18T09:30:45",
        "2026-09-18 09:30:45",
        datetime(2026, 9, 18, 9, 30, 45),
        datetime(2026, 9, 18, 9, 30, 45, 987654),
        "2026-09-18T09:30:45.987654Z",
        datetime(2026, 9, 18, 9, 30, 45, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_time_json_uses_backend_format(field: str, value: str | datetime) -> None:
    item = SwapOrderOpenApiBaseSaveReqVO.model_validate({field: value})
    expected = {field: "2026-09-18 09:30:45"}

    assert item.model_dump(mode="json", exclude_none=True) == expected
    assert json.loads(item.model_dump_json(exclude_none=True)) == expected


@pytest.mark.parametrize("field", ["placeOrderStartTime", "placeOrderEndTime"])
@pytest.mark.parametrize("value, expected_time", [("14:00", "14:00:00"), ("14:30:45", "14:30:45")])
def test_short_time_json_preserves_promoted_date(
    field: str, value: str, expected_time: str
) -> None:
    item = SwapOrderOpenApiBaseSaveReqVO.model_validate({field: value})
    parsed = item.model_dump()[field]
    assert isinstance(parsed, datetime)

    assert item.model_dump(mode="json")[field] == f"{parsed.date()} {expected_time}"


def test_time_python_dump_preserves_datetime_and_precision() -> None:
    value = datetime(2026, 9, 18, 9, 30, 45, 987654, timezone(timedelta(hours=8)))
    item = SwapOrderOpenApiBaseSaveReqVO(
        placeOrderStartTime=value, placeOrderEndTime=value
    )

    assert item.model_dump(exclude_none=True) == {
        "placeOrderStartTime": value,
        "placeOrderEndTime": value,
    }


def test_none_times_are_null_or_omitted_in_json() -> None:
    item = SwapOrderOpenApiBaseSaveReqVO(placeOrderStartTime=None, placeOrderEndTime=None)

    assert item.model_dump(mode="json")["placeOrderStartTime"] is None
    assert item.model_dump(mode="json")["placeOrderEndTime"] is None
    assert item.model_dump(mode="json", exclude_none=True) == {}
    assert json.loads(item.model_dump_json(exclude_none=True)) == {}


@pytest.mark.asyncio
async def test_operate_sends_backend_time_format_for_all_orders() -> None:
    seen: list[httpx.Request] = []
    response = {"code": 0, "msg": "ok", "data": {"orderId": "H-1"}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response)

    req = SwapOrderOpenApiSaveReqVO.model_validate({
        "type": "place_order_request",
        "orderList": [
            {
                "placeOrderStartTime": "2026-09-18T09:30:00.123456+08:00",
                "placeOrderEndTime": "2026-09-18T15:00:00+08:00",
            },
            {"placeOrderStartTime": "2026-09-19 10:00:00", "placeOrderEndTime": None},
            {"placeOrderEndTime": "2026-09-19 11:00:00"},
            {},
        ],
        "conversationId": "test",
        "messageId": 1,
        "messageContent": "test",
        "rawContent": "test",
        "userId": "test",
        "roomId": "test",
    })
    client = SwapClientHttpx(
        base_url="http://swap.test", token="test", timeout=1,
        transport=httpx.MockTransport(handler), dry_run=False,
    )

    assert await client.operate(req) == response
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/admin-api/swap-order/operate"
    assert json.loads(seen[0].content)["orderList"] == [
        {"placeOrderStartTime": "2026-09-18 09:30:00", "placeOrderEndTime": "2026-09-18 15:00:00"},
        {"placeOrderStartTime": "2026-09-19 10:00:00"},
        {"placeOrderEndTime": "2026-09-19 11:00:00"},
        {},
    ]
