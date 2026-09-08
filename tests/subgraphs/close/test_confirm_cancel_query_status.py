"""close.confirm_cancel + close.query_status 节点测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import (
    confirm_cancel as cc_module,
)
from app.subgraphs.close import (
    query_status as qs_module,
)
from app.subgraphs.close.confirm_cancel import close_confirm_cancel
from app.subgraphs.close.models import ConfirmCancelParams, QueryStatusParams
from app.subgraphs.close.query_status import close_query_status


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, module: object, value: object
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(
        module,
        "call_close_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )
    return fake_llm.ainvoke


# ============================================================
# Pydantic 模型
# ============================================================


class TestConfirmCancelParams:
    def test_default_empty_list(self) -> None:
        params = ConfirmCancelParams()
        assert params.confirmCancelOrderNoList == []

    def test_with_orders(self) -> None:
        params = ConfirmCancelParams(
            confirmCancelOrderNoList=["CO-20260304-AAAA", "CO-20260304-BBBB"]
        )
        assert len(params.confirmCancelOrderNoList) == 2

    def test_extra_fields_ignored(self) -> None:
        params = ConfirmCancelParams.model_validate(
            {"confirmCancelOrderNoList": [], "garbage": "x"}
        )
        assert params.confirmCancelOrderNoList == []


class TestQueryStatusParams:
    def test_default_empty_list(self) -> None:
        params = QueryStatusParams()
        assert params.queryOrderNoList == []

    def test_with_orders(self) -> None:
        params = QueryStatusParams(
            queryOrderNoList=["CO-20260305-59772C14"]
        )
        assert params.queryOrderNoList == ["CO-20260305-59772C14"]

    def test_extra_fields_ignored(self) -> None:
        params = QueryStatusParams.model_validate(
            {"queryOrderNoList": [], "garbage": "x"}
        )
        assert params.queryOrderNoList == []


# ============================================================
# close.confirm_cancel 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseConfirmCancelNode:
    async def test_extracts_orders_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ConfirmCancelParams(
            confirmCancelOrderNoList=[
                "CO-20260304-AAAA",
                "CO-20260304-BBBB",
            ]
        )
        _patch_llm(monkeypatch, cc_module, params)
        result = await close_confirm_cancel(
            {
                "raw_text": "确认撤单",
                "quote_content": (
                    "1. CO-20260304-AAAA\n2. CO-20260304-BBBB"
                ),
            }
        )
        assert result["confirm"]["action"] == "cancel_close"
        assert len(result["confirm"]["confirmCancelOrderNoList"]) == 2

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            cc_module,
            ConfirmCancelParams(confirmCancelOrderNoList=["CO-1"]),
        )
        result = await close_confirm_cancel(
            {"raw_text": "确认撤销", "quote_content": "CO-1"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_confirm_cancel"
        assert "orders=1" in trace[0].decision

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
            cc_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_confirm_cancel(
            {"raw_text": "x", "quote_content": ""}
        )
        assert result.get("error") is not None
        assert result["error"].node == "close_confirm_cancel"


# ============================================================
# close.query_status 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseQueryStatusNode:
    async def test_extracts_query_orders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = QueryStatusParams(
            queryOrderNoList=["CO-20260305-59772C14"]
        )
        _patch_llm(monkeypatch, qs_module, params)
        result = await close_query_status(
            {"raw_text": "查询 CO-20260305-59772C14 状态"}
        )
        assert result["query_filter"]["queryOrderNoList"] == [
            "CO-20260305-59772C14"
        ]

    async def test_empty_orders_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, qs_module, QueryStatusParams())
        result = await close_query_status({"raw_text": "查"})
        assert result["query_filter"]["queryOrderNoList"] == []

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = QueryStatusParams(
            queryOrderNoList=["CO-A", "CO-B", "CO-C"]
        )
        _patch_llm(monkeypatch, qs_module, params)
        result = await close_query_status(
            {"raw_text": "查 CO-A CO-B CO-C 状态"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_query_status"
        assert "orders=3" in trace[0].decision

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
            qs_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_query_status({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "close_query_status"
