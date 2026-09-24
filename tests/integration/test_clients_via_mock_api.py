"""业务 client → mock_api 内存集成测试（基于 Mock API 的客户端契约验证层）。

覆盖 3 个 client 的主要 endpoint：
- OptionClient: operate（4 个代表 type）+ query_close_orders
- SwapClient: operate（4 个代表 type）+ get / get_conversation_orders
- TickerClient: list_counterparty

每个 case 验证：
1. client 实际发的 URL 拼对（contract §1-§3）
2. payload 形状 mock_api 能 422 校验通过
3. mock_api 响应 client 原样 dict 透传（不 raise）

不验证业务正确性（mock_api 返回的是固定 stub，不是真业务逻辑）。
"""
from __future__ import annotations

import pytest

from app.tools.models import (
    GoatsOrderDirection,
    GoatsPriceType,
    GoatsTransactionType,
)
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    OptionIntentionType,
)
from app.tools.swap_client import (
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)

# ============================================================
# 测试用上下文（最小 BotContext 字段集）
# ============================================================


def _bot_ctx() -> dict:
    return {
        "conversationId": "conv-int-001",
        "messageId": 1,
        "messageContent": "test",
        "rawContent": "test",
        "userId": "u-int",
        "roomId": "r-int",
    }


# ============================================================
# OptionClient · operate
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        OptionIntentionType.NEW_INQUIRY,
        OptionIntentionType.PLACE_ORDER_FROM_QUOTE,
        OptionIntentionType.CANCEL_ORDER_REQUEST,
        OptionIntentionType.QUERY_ORDER_STATUS,
    ],
)
async def test_option_operate_4_intents(option_client, intent: OptionIntentionType) -> None:
    req = FinancialOrderOpenApiSaveReqVO(
        type=intent,
        orderList=[
            FinancialOrderOpenApiBaseSaveReqVO(
                placeOrderWindCode="00700.HK",
                placeOrderQuantity=100,
                placeOrderOrderDirection=GoatsOrderDirection.BUY,
                placeOrderPriceType=GoatsPriceType.LIMIT_ORDER,
            )
        ],
        **_bot_ctx(),
    )
    result = await option_client.operate(req)
    assert isinstance(result, dict)
    # mock_api 默认返回 code=0 表示业务路径通
    assert result["code"] == 0, f"intent={intent} 失败: {result}"


async def test_option_query_close_orders_ok(option_client) -> None:
    result = await option_client.query_close_orders(
        order_ids=["FO-1001"], contract_codes=["00700.HK"]
    )
    assert isinstance(result, dict)
    assert result["code"] == 0


# ============================================================
# SwapClient · operate / get / conversation_orders
# ============================================================


@pytest.mark.parametrize(
    "intent",
    [
        SwapIntentionType.PLACE_ORDER_REQUEST,
        SwapIntentionType.CONFIRM_ORDER,
        SwapIntentionType.CANCEL_ORDER_REQUEST,
        SwapIntentionType.QUERY_ORDER_STATUS,
    ],
)
async def test_swap_operate_4_intents(swap_client, intent: SwapIntentionType) -> None:
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
    result = await swap_client.operate(req)
    assert isinstance(result, dict)
    assert result["code"] == 0


async def test_swap_get_by_order_id(swap_client) -> None:
    result = await swap_client.get(order_id="SW-1001")
    assert isinstance(result, dict)
    assert result["code"] == 0


async def test_swap_get_conversation_orders(swap_client) -> None:
    result = await swap_client.get_conversation_orders(conversation_id="conv-int-001")
    assert isinstance(result, dict)
    assert result["code"] == 0


# ============================================================
# TickerClient · counterparty
# ============================================================


async def test_ticker_list_counterparty(ticker_client) -> None:
    rows = await ticker_client.list_counterparty(room_id="r-int")
    assert isinstance(rows, list)
    # mock_api 返回固定列表


# ============================================================
# Transport 注入不影响生产路径 · 烟测
# ============================================================


def test_client_without_transport_uses_real_httpx(option_client, swap_client, ticker_client) -> None:
    """transport=None（生产路径）时 _client_kwargs 不带 transport 键。"""
    # 重新构造一份 transport=None 的 client 验证生产路径
    from app.tools.option_client import OptionClientHttpx

    prod_client = OptionClientHttpx(base_url="http://prod", token="x", transport=None)
    kw = prod_client._client_kwargs()
    assert "transport" not in kw
    assert kw["trust_env"] is False  # 生产不读环境代理
    from app.config import get_settings
    assert kw["timeout"] == get_settings().backend_timeout_seconds


def test_client_with_transport_passes_through(option_client) -> None:
    """transport 注入 → _client_kwargs 含 transport 键。"""
    kw = option_client._client_kwargs()
    assert "transport" in kw
    assert kw["transport"] is not None


# ============================================================
# GoatsAgentClient（DSL v2 fast_query 前置分支，2026-08 新增）
# ============================================================


async def test_goats_agent_parse_rfq_instrument(goats_agent_client) -> None:
    """快速询价 RFQ 解析：业务 200 → code=0，仅解包后的 data 可喂 optionRfq。"""
    out = await goats_agent_client.parse_rfq_instrument(
        "快速询价：欧式看涨，600519.SH，100，1M", "room-int-1", "user-int-1"
    )
    assert out["code"] == 0
    assert out["errMsg"] == ""
    obj = out["api_data_result_obj"]
    assert obj is not None
    assert "productType" in obj  # GoatsOptionRfqReqVO 最低消费字段
    assert "errCode" not in obj
    assert "data" not in obj


async def test_goats_agent_query_instruction(goats_agent_client) -> None:
    """存量兼容查询：200 → code=0，errMsg 恒为静默哨兵。"""
    from app.tools.goats_agent_client import IGNORE_REPLY_SENTINEL

    out = await goats_agent_client.query_instruction(
        "有多少存量单", "room-int-1", "user-int-1"
    )
    assert out["code"] == 0
    assert out["errMsg"] == IGNORE_REPLY_SENTINEL
    assert out["api_data_result_obj"] is not None
