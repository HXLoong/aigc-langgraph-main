"""option.extract_confirm_place 节点测试（确认下单，确定性提取，无 LLM）。

与 extract_place 同规约，仅少 hasFastExecutionIntent（A 类不含该字段）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_confirm_place as ecp_module
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place

_QUOTE_CARD = (
    "-----场外期权询价详情-----\r\n"
    "Q-20250616-000011\r\n"
    "标的代码：300098.SZ；欧式看涨；80%\r\n"
    "期限待补充，请引用本消息回复期限。如需下单，请提供建仓参数。"
)


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """patch 后端调用 + 禁止 LLM。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(ecp_module, "call_option_backend", backend)

    def _forbid(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    monkeypatch.setattr(ecp_module, "get_qwen_thinking", _forbid, raising=False)
    return backend


def _item(result: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return result["confirm"]["orderList"][index]


@pytest.mark.asyncio
class TestOptionExtractConfirmPlaceNode:
    async def test_confirm_with_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "quote_content": _QUOTE_CARD}
        )
        assert result["confirm"]["action"] == "place"
        item = _item(result)
        assert item["orderId"] == "Q-20250616-000011"
        assert item["stockCode"] == "300098.SZ"
        assert item["optionType"] == "欧式看涨"
        assert item["strikePercentage"] == 80.0
        assert "hasFastExecutionIntent" not in item
        assert backend.await_args.kwargs["intent"] == "confirm_order"

    async def test_confirm_with_supplementary_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单 限价12", "quote_content": _QUOTE_CARD}
        )
        item = _item(result)
        assert item["orderType"] == "限价单"
        assert item["limitPrice"] == 12.0
        assert item["orderId"] == "Q-20250616-000011"

    async def test_raw_tenor_overrides_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_confirm_place(
            {"raw_text": "2M 确认下单", "quote_content": _QUOTE_CARD}
        )
        assert _item(result)["tenor"] == "2M"

    async def test_multiple_order_ids_from_quote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "quote_content": "Q-20250616-000011、Q-20250616-000012"}
        )
        order_list = result["confirm"]["orderList"]
        assert [o["orderId"] for o in order_list] == [
            "Q-20250616-000011",
            "Q-20250616-000012",
        ]

    async def test_no_order_keeps_placeholder_item(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_confirm_place({"raw_text": "确认下单"})
        order_list = result["confirm"]["orderList"]
        assert len(order_list) == 1
        assert order_list[0]["orderId"] is None

    async def test_writes_trace_and_passes_backend_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "quote_content": "Q-20250616-000011、Q-20250616-000012"}
        )
        trace = result["trace"]
        assert trace[0].node == "option_extract_confirm_place"
        assert "deterministic" in trace[0].decision
        assert "action=place" in trace[0].decision
        assert "orders=2" in trace[0].decision
        assert backend.await_args.kwargs["order_list"] == result["confirm"]["orderList"]
