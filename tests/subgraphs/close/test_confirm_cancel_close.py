"""close.confirm_close + close.cancel_close 节点测试（mock LLM）。

两个节点结构高度相似（订单号列表提取），合并到一份测试文件。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.close import cancel_close as cancel_module
from app.subgraphs.close import confirm_close as confirm_module
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_close import close_confirm_close
from app.subgraphs.close.models import CancelCloseParams, ConfirmCloseParams


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, module: object, return_value: object,
    fn: str = "get_qwen_thinking",
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=return_value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, fn, lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# Pydantic 模型
# ============================================================


class TestParamsModels:
    def test_confirm_close_params_default_empty_list(self) -> None:
        params = ConfirmCloseParams()
        assert params.confirmOrderNoList == []

    def test_confirm_close_params_with_orders(self) -> None:
        params = ConfirmCloseParams(
            confirmOrderNoList=["CO-20260304-4FE9C941", "CO-20260304-E2BA7501"]
        )
        assert len(params.confirmOrderNoList) == 2

    def test_cancel_close_params_default_empty_list(self) -> None:
        params = CancelCloseParams()
        assert params.cancelOrderNoList == []

    def test_cancel_close_params_with_orders(self) -> None:
        params = CancelCloseParams(
            cancelOrderNoList=["CO-20260304-759125AD"]
        )
        assert params.cancelOrderNoList == ["CO-20260304-759125AD"]

    def test_confirm_close_extra_fields_ignored(self) -> None:
        params = ConfirmCloseParams.model_validate(
            {"confirmOrderNoList": [], "garbage": "x"}
        )
        assert params.confirmOrderNoList == []

    def test_cancel_close_extra_fields_ignored(self) -> None:
        params = CancelCloseParams.model_validate(
            {"cancelOrderNoList": [], "garbage": "x"}
        )
        assert params.cancelOrderNoList == []


# ============================================================
# close.confirm_close 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseConfirmCloseNode:
    async def test_extracts_orders_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ConfirmCloseParams(
            confirmOrderNoList=["CO-20260304-E2BA7501"]
        )
        _patch_llm(monkeypatch, confirm_module, params, fn="get_qwen_thinking")
        result = await close_confirm_close(
            {
                "raw_text": "确认平仓第二笔",
                "quote_content": (
                    "1. CO-20260304-4FE9C941\n2. CO-20260304-E2BA7501"
                ),
            }
        )
        assert result["confirm"]["action"] == "close"
        assert result["confirm"]["confirmOrderNoList"] == [
            "CO-20260304-E2BA7501"
        ]

    async def test_empty_orders_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, confirm_module, ConfirmCloseParams(), fn="get_qwen_thinking")
        result = await close_confirm_close(
            {"raw_text": "确认", "quote_content": ""}
        )
        assert result["confirm"]["confirmOrderNoList"] == []

    async def test_writes_trace_with_order_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ConfirmCloseParams(
            confirmOrderNoList=["CO-1", "CO-2", "CO-3"]
        )
        _patch_llm(monkeypatch, confirm_module, params, fn="get_qwen_thinking")
        result = await close_confirm_close({"raw_text": "确认平仓全部"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_confirm_close"
        assert "orders=3" in trace[0].decision

    async def test_passes_quote_to_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ainvoke = _patch_llm(
            monkeypatch, confirm_module, ConfirmCloseParams(), fn="get_qwen_thinking"
        )
        await close_confirm_close(
            {
                "raw_text": "确认第一笔",
                "quote_content": "订单 CO-20260304-XYZ",
            }
        )
        messages = ainvoke.call_args[0][0]
        user_content = messages[-1][1]
        assert "用户发送消息：确认第一笔" in user_content
        assert "用户引用消息：订单 CO-20260304-XYZ" in user_content


# ============================================================
# close.cancel_close 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseCancelCloseNode:
    async def test_extracts_cancel_orders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = CancelCloseParams(
            cancelOrderNoList=["CO-20260304-759125AD"]
        )
        _patch_llm(monkeypatch, cancel_module, params)
        result = await close_cancel_close(
            {
                "raw_text": "撤销第一笔",
                "quote_content": "1. CO-20260304-759125AD",
            }
        )
        assert result["cancel_params"]["cancelOrderNoList"] == [
            "CO-20260304-759125AD"
        ]

    async def test_empty_orders_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, cancel_module, CancelCloseParams())
        result = await close_cancel_close(
            {"raw_text": "撤", "quote_content": ""}
        )
        assert result["cancel_params"]["cancelOrderNoList"] == []

    async def test_writes_trace_with_order_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = CancelCloseParams(cancelOrderNoList=["CO-A", "CO-B"])
        _patch_llm(monkeypatch, cancel_module, params)
        result = await close_cancel_close({"raw_text": "撤销 CO-A 和 CO-B"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_cancel_close"
        assert "orders=2" in trace[0].decision

    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            cancel_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_cancel_close(
            {"raw_text": "撤", "quote_content": ""}
        )
        assert result.get("error") is not None
        assert result["error"].node == "close_cancel_close"
