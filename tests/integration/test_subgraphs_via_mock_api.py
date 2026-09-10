"""业务子图 backend → mock_api 真路径集成测试（PR #110 / Tony 问题 2 彻底解答）。

PR #109 补了 client 层 → mock_api 集成（tests/integration/test_clients_via_mock_api.py），
本文件补 **业务 backend 层 → 真 client → mock_api** 全链路：

  state(business) → call_*_backend → real *ClientHttpx → ASGITransport → mock_api

与之前 tests/subgraphs/swap/test_backend.py 的 unittest.mock 链路对比：

  - 旧: monkeypatch SwapClientHttpx → fake_client.operate = AsyncMock(return CommonResult)
    **不测**：真实 client 构造 / URL 拼装 / payload 形状
  - 新（本文件）: monkeypatch SwapClientHttpx → 返回 **真实** SwapClientHttpx(transport=ASGITransport)
    **能测**：业务逻辑 + client + payload + mock_api 响应解析全链路

不替代旧测试——单元测试覆盖快速反馈 + 边界异常；本文件覆盖真路径集成。

仅覆盖 P0 子图（示范），后续按需扩展到 P1/P2 节点。
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.subgraphs.option import backend as option_backend
from app.subgraphs.swap import backend as swap_backend
from mock_api.server import app as mock_app

# ============================================================
# 共用 state 工厂
# ============================================================


def _full_state(raw: str = "测试输入") -> dict[str, Any]:
    return {
        "raw_text": raw,
        "conversation_id": "conv-int-100",
        "message_id": 100,
        "message_content": raw,
        "user_id": "u-int",
        "room_id": "r-int",
    }


def _make_real_swap_client_with_mock_api():
    """构造真 SwapClientHttpx，但 httpx 走 ASGITransport(mock_api)。"""
    from app.tools.swap_client import SwapClientHttpx

    transport = httpx.ASGITransport(app=mock_app)
    return SwapClientHttpx(
        base_url="http://mock",
        token="test-token",
        transport=transport,
    )


def _make_real_option_client_with_mock_api():
    from app.tools.option_client import OptionClientHttpx

    transport = httpx.ASGITransport(app=mock_app)
    return OptionClientHttpx(
        base_url="http://mock",
        token="test-token",
        transport=transport,
    )


# ============================================================
# Swap backend × mock_api · 6 个 SwapIntentionType
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        "place_order_request",
        "confirm_order",
        "cancel_order_request",
        "confirm_cancel_order",
        "confirm_modify_order",
        "query_order_status",
    ],
)
async def test_swap_backend_real_path_via_mock_api(
    intent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """业务 backend → 真 client → ASGITransport → mock_api 全链路 6 个 swap intent。

    这条链路任何一环坏（payload 字段名错、URL 写错、CommonResult 反序列化变化）
    都会在这里捕获 —— 与之前 unittest.mock 版本互补。
    """
    monkeypatch.setattr(
        swap_backend, "SwapClientHttpx",
        _make_real_swap_client_with_mock_api,
    )
    result = await swap_backend.call_swap_backend(
        _full_state(f"互换 {intent}"),
        intent=intent,
        order_list=[{"placeOrderWindCode": "600519.SH", "placeOrderQuantity": 1000}],
    )
    # mock_api 默认返回 code=0 表示走通
    assert result["api_code"] == 0, f"intent={intent} 链路失败: {result}"
    assert "api_result" in result


async def test_swap_backend_missing_context_short_circuits(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """state 缺 conversation_id → 不调真 client（fail-safe），但不应崩。"""
    monkeypatch.setattr(
        swap_backend, "SwapClientHttpx",
        _make_real_swap_client_with_mock_api,
    )
    result = await swap_backend.call_swap_backend(
        {"raw_text": "x"},  # 缺 conversation_id / room_id / user_id
        intent="place_order_request",
    )
    assert result == {}


# ============================================================
# Option backend × mock_api · 代表 intent
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        "new_inquiry",
        "place_order_from_quote",
        "confirm_order",
        "cancel_order_request",
        "request_cancel_order",
        "confirm_cancel_order",
        "request_modify_order",
        "confirm_modify_order",
        "query_order_status",
        "close_order_query",
        "close_order_request",
        "close_order_confirm",
        "close_order_cancel_request",
        "close_order_cancel_confirm",
        "close_order_order_query",
        "unknown_intent",
    ],
)
async def test_option_backend_real_path_via_mock_api(
    intent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """16 个 OptionIntentionType 全链路。"""
    monkeypatch.setattr(
        option_backend, "OptionClientHttpx",
        _make_real_option_client_with_mock_api,
    )
    result = await option_backend.call_option_backend(
        _full_state(f"期权 {intent}"),
        intent=intent,
        order_list=[{"placeOrderWindCode": "00700.HK", "placeOrderQuantity": 100}],
    )
    assert result["api_code"] == 0, f"intent={intent} 链路失败: {result}"


async def test_option_backend_with_option_rfq(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """new_inquiry 带 optionRfq 字段（参与型 / 雪球 / 香草等询价载荷）。"""
    monkeypatch.setattr(
        option_backend, "OptionClientHttpx",
        _make_real_option_client_with_mock_api,
    )
    result = await option_backend.call_option_backend(
        _full_state("参与型看涨 腾讯 1个月 80%"),
        intent="new_inquiry",
        option_rfq={
            "productType": "PARTICIPATING_CALL",
            "chatInstrument": "00700.HK",
            "tenor": ["1M"],
            "strike": ["80%"],
        },
    )
    assert result["api_code"] == 0


async def test_option_backend_missing_context_short_circuits(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        option_backend, "OptionClientHttpx",
        _make_real_option_client_with_mock_api,
    )
    from app.tools.exceptions import MissingBackendContextError

    with pytest.raises(MissingBackendContextError):
        await option_backend.call_option_backend(
            {"raw_text": "x"}, intent="new_inquiry"
        )


# ============================================================
# 链路完整性 · payload 格式与 mock_api 校验对齐
# ============================================================


async def test_swap_payload_passes_mock_api_validation(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """如果 call_swap_backend 拼的 payload 缺必填字段，mock_api 会返 422。
    本测试保证 backend 拼的字段始终对齐 mock_api FastAPI 校验。
    """
    monkeypatch.setattr(
        swap_backend, "SwapClientHttpx",
        _make_real_swap_client_with_mock_api,
    )
    # 不带 orderList 的极端 case（business edge：意图明确但参数不全）
    result = await swap_backend.call_swap_backend(
        _full_state(),
        intent="query_order_status",
        order_list=[],
    )
    # mock_api 校验通过 + business 走 query 路径 = code 0（即使 orderList 空）
    assert result["api_code"] == 0


async def test_option_payload_passes_mock_api_validation(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        option_backend, "OptionClientHttpx",
        _make_real_option_client_with_mock_api,
    )
    result = await option_backend.call_option_backend(
        _full_state(),
        intent="new_inquiry",
        order_list=[],
    )
    assert result["api_code"] == 0
