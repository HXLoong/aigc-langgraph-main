"""F4.1 shadow 双跑 dry-run 模式测试 · OptionClient / SwapClient 写类拦截。

测试范围：
- dry_run=True 时写类 intent 被拦截返 fake CommonResult
- dry_run=True 时 read 类 intent 仍真调 mock_api
- dry_run=False（生产路径）所有 intent 真调
- 拦截时 metrics emit_dry_run_intercept 计数
- dry_run 参数从 settings.dry_run_backend 默认读取

不测：
- query_close_orders / get / get_conversation_orders 等独立 read endpoint（本就不在拦截范围）
- TickerClient（全 read endpoint，不需 dry-run）
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.tools.models import (
    CommonResult,
    GoatsOrderDirection,
    GoatsPriceType,
    GoatsTransactionType,
)
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)
from app.tools.swap_client import (
    SwapClientHttpx,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)
from mock_api.server import app as mock_app


@pytest.fixture(autouse=True)
def _reset_dry_run_counter():
    from app.observability import metrics as M

    M.get_collector()._counters[M.METRIC_DRY_RUN_INTERCEPT_TOTAL].clear()
    yield
    M.get_collector()._counters[M.METRIC_DRY_RUN_INTERCEPT_TOTAL].clear()


def _bot_ctx() -> dict:
    return {
        "conversationId": "dry-001",
        "messageId": 1,
        "messageContent": "test",
        "rawContent": "test",
        "userId": "u-1",
        "roomId": "r-1",
    }


def _mock_api_client_kwargs(dry_run: bool) -> dict:
    return {
        "base_url": "http://mock",
        "token": "test",
        "transport": httpx.ASGITransport(app=mock_app),
        "dry_run": dry_run,
    }


# ============================================================
# OptionClient · 写类 intent 被拦截
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        # 写类（应被拦截）
        OptionIntentionType.PLACE_ORDER_FROM_QUOTE,
        OptionIntentionType.CONFIRM_ORDER,
        OptionIntentionType.CANCEL_ORDER_REQUEST,
        OptionIntentionType.REQUEST_CANCEL_ORDER,
        OptionIntentionType.CONFIRM_CANCEL_ORDER,
        OptionIntentionType.REQUEST_MODIFY_ORDER,
        OptionIntentionType.CONFIRM_MODIFY_ORDER,
        OptionIntentionType.CLOSE_ORDER_REQUEST,
        OptionIntentionType.CLOSE_ORDER_CONFIRM,
        OptionIntentionType.CLOSE_ORDER_CANCEL_REQUEST,
        OptionIntentionType.CLOSE_ORDER_CANCEL_CONFIRM,
    ],
)
async def test_option_dry_run_intercepts_write_intents(intent) -> None:
    client = OptionClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = FinancialOrderOpenApiSaveReqVO(
        type=intent,
        orderList=[
            FinancialOrderOpenApiBaseSaveReqVO(
                placeOrderWindCode="00700.HK", placeOrderQuantity=100,
                placeOrderOrderDirection=GoatsOrderDirection.BUY,
                placeOrderPriceType=GoatsPriceType.LIMIT_ORDER,
            )
        ],
        **_bot_ctx(),
    )
    result = await client.operate(req)
    assert isinstance(result, CommonResult)
    assert result.code == 0
    assert result.msg == "dry-run intercepted"
    assert result.data["orderId"].startswith("DRY-RUN-")


@pytest.mark.parametrize(
    "intent",
    [
        # read 类（不拦截，真调 mock_api）
        OptionIntentionType.NEW_INQUIRY,
        OptionIntentionType.QUERY_ORDER_STATUS,
        OptionIntentionType.CLOSE_ORDER_QUERY,
        OptionIntentionType.CLOSE_ORDER_ORDER_QUERY,
        OptionIntentionType.UNKNOWN_INTENT,
    ],
)
async def test_option_dry_run_passes_through_read_intents(intent) -> None:
    """read 类即使 dry_run=True 也真调 mock_api（返回 code=0 但不是 'dry-run intercepted'）。"""
    client = OptionClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = FinancialOrderOpenApiSaveReqVO(
        type=intent,
        orderList=[],
        **_bot_ctx(),
    )
    result = await client.operate(req)
    assert result.code == 0
    assert result.msg != "dry-run intercepted", (
        f"read intent {intent} 不应被 dry-run 拦截"
    )


async def test_option_dry_run_emits_metric() -> None:
    """拦截 N 次写类 → metrics counter 增 N。"""
    from app.observability.metrics import (
        METRIC_DRY_RUN_INTERCEPT_TOTAL,
        get_collector,
    )

    client = OptionClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType.PLACE_ORDER_FROM_QUOTE,
        orderList=[],
        **_bot_ctx(),
    )
    await client.operate(req)
    await client.operate(req)

    cnt = get_collector().get_counter(
        METRIC_DRY_RUN_INTERCEPT_TOTAL,
        {"client": "option", "operation": "operate:place_order_from_quote"},
    )
    assert cnt == 2


async def test_option_dry_run_false_does_not_intercept() -> None:
    """dry_run=False（生产路径）所有 intent 都真调。"""
    client = OptionClientHttpx(**_mock_api_client_kwargs(dry_run=False))
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType.PLACE_ORDER_FROM_QUOTE,
        orderList=[],
        **_bot_ctx(),
    )
    result = await client.operate(req)
    # mock_api 返回 code=0（业务正常），不应是"dry-run intercepted"
    assert result.msg != "dry-run intercepted"


# ============================================================
# SwapClient · 写类 intent 被拦截
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        SwapIntentionType.PLACE_ORDER_REQUEST,
        SwapIntentionType.CONFIRM_ORDER,
        SwapIntentionType.CANCEL_ORDER_REQUEST,
        SwapIntentionType.CONFIRM_CANCEL_ORDER,
        SwapIntentionType.CONFIRM_MODIFY_ORDER,
    ],
)
async def test_swap_dry_run_intercepts_write_intents(intent) -> None:
    client = SwapClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = SwapOrderOpenApiSaveReqVO(
        type=intent,
        orderList=[
            SwapOrderOpenApiBaseSaveReqVO(
                placeOrderWindCode="600519.SH",
                placeOrderTransactionType=GoatsTransactionType.A_SHARE,
                placeOrderQuantity=1000,
                placeOrderOrderDirection=GoatsOrderDirection.BUY,
                placeOrderPriceType=GoatsPriceType.LIMIT_ORDER,
            )
        ],
        **_bot_ctx(),
    )
    result = await client.operate(req)
    assert result.msg == "dry-run intercepted"
    assert result.data["orderId"].startswith("DRY-RUN-")


@pytest.mark.parametrize(
    "intent",
    [
        SwapIntentionType.QUERY_ORDER_STATUS,
        SwapIntentionType.UNKNOWN_INTENT,
    ],
)
async def test_swap_dry_run_passes_through_read_intents(intent) -> None:
    client = SwapClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = SwapOrderOpenApiSaveReqVO(
        type=intent,
        orderList=[],
        **_bot_ctx(),
    )
    result = await client.operate(req)
    assert result.msg != "dry-run intercepted"


async def test_swap_dry_run_emits_metric() -> None:
    from app.observability.metrics import (
        METRIC_DRY_RUN_INTERCEPT_TOTAL,
        get_collector,
    )

    client = SwapClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    req = SwapOrderOpenApiSaveReqVO(
        type=SwapIntentionType.CANCEL_ORDER_REQUEST,
        orderList=[],
        **_bot_ctx(),
    )
    await client.operate(req)

    cnt = get_collector().get_counter(
        METRIC_DRY_RUN_INTERCEPT_TOTAL,
        {"client": "swap", "operation": "operate:cancel_order_request"},
    )
    assert cnt == 1


# ============================================================
# 从 settings 默认读取
# ============================================================


def test_dry_run_defaults_to_settings_value() -> None:
    """dry_run 不传时从 Settings.dry_run_backend 读。"""
    from types import SimpleNamespace

    fake_settings = SimpleNamespace(
        otc_api_base_url="http://x",
        otc_api_secret="x",
        dry_run_backend=True,
    )
    with patch("app.config.get_settings", return_value=fake_settings):
        client = OptionClientHttpx()
    assert client._dry_run is True


def test_dry_run_explicit_overrides_settings() -> None:
    """显式传 dry_run=False 覆盖 settings.dry_run_backend=True。"""
    from types import SimpleNamespace

    fake_settings = SimpleNamespace(
        otc_api_base_url="http://x",
        otc_api_secret="x",
        dry_run_backend=True,
    )
    with patch("app.config.get_settings", return_value=fake_settings):
        client = OptionClientHttpx(dry_run=False)
    assert client._dry_run is False


# ============================================================
# read endpoint 不受 dry_run 影响
# ============================================================


async def test_option_query_close_orders_never_intercepted() -> None:
    """query_close_orders 是独立 read endpoint，dry_run=True 也不拦截。"""
    client = OptionClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    result = await client.query_close_orders(
        order_ids=["FO-1"], contract_codes=["00700.HK"]
    )
    assert result.code == 0
    assert result.msg != "dry-run intercepted"


async def test_swap_get_never_intercepted() -> None:
    """swap.get(order_id) 是独立 read endpoint，dry_run=True 也不拦截。"""
    client = SwapClientHttpx(**_mock_api_client_kwargs(dry_run=True))
    result = await client.get(order_id="SW-1")
    assert result.code == 0
    assert result.msg != "dry-run intercepted"
