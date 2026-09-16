"""close.confirm_cancel + close.query_status 节点测试（确定性提取，无 LLM）。

行为 1:1 对照原提示词规约：
- confirm_cancel：quote 全量提取（@提及 / 引号包裹 / UUID 均不影响）；用户指定子集（单号 / 序号）→ 仅取子集；不允许无故空列表
- query_status：仅从 raw 提取全部 CO- 单号（去重、统一大写）；均无 → []
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.close import confirm_cancel as cc_module
from app.subgraphs.close import query_status as qs_module
from app.subgraphs.close.confirm_cancel import close_confirm_cancel
from app.subgraphs.close.query_status import close_query_status

_QUOTE_TWO = "1. CO-20260304-4FE9C941\n2. CO-20260304-E2BA7501"


def _patch(monkeypatch: pytest.MonkeyPatch, module: object) -> AsyncMock:
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(module, "call_close_backend", backend)

    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    monkeypatch.setattr(module, "get_qwen_thinking", _forbid, raising=False)
    return backend


# ============================================================
# close.confirm_cancel 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseConfirmCancelNode:
    async def test_unspecified_takes_all_quote_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {"raw_text": "确认撤单", "quote_content": _QUOTE_TWO}
        )
        assert result["confirm"]["action"] == "cancel_close"
        assert result["confirm"]["confirmCancelOrderNoList"] == [
            "CO-20260304-4FE9C941",
            "CO-20260304-E2BA7501",
        ]

    async def test_mention_prefix_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {
                "raw_text": "@场外AI交易助手测试C 确认撤单",
                "quote_content": (
                    "期权平仓订单CO-20260305-396218FE：已收到您的撤单请求。"
                    " 如需继续，请引用本消息并回复【确认撤单】"
                ),
            }
        )
        assert result["confirm"]["confirmCancelOrderNoList"] == [
            "CO-20260305-396218FE"
        ]

    async def test_quote_uuid_not_confused_with_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {
                "raw_text": "确认撤单",
                "quote_content": (
                    "A场外交易助手: @王五 (65250bd1-a358-40db-ac7b-289d6b84a6b3) "
                    "期权平仓订单CO-20260305-396218FE：已收到您的撤单请求。"
                ),
            }
        )
        assert result["confirm"]["confirmCancelOrderNoList"] == [
            "CO-20260305-396218FE"
        ]

    async def test_raw_order_id_selects_subset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {
                "raw_text": "确认撤单 CO-20260304-4FE9C941",
                "quote_content": _QUOTE_TWO,
            }
        )
        assert result["confirm"]["confirmCancelOrderNoList"] == [
            "CO-20260304-4FE9C941"
        ]

    async def test_ordinal_selects_subset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {"raw_text": "确认撤单第二笔", "quote_content": _QUOTE_TWO}
        )
        assert result["confirm"]["confirmCancelOrderNoList"] == [
            "CO-20260304-E2BA7501"
        ]

    async def test_unresolved_ordinal_does_not_expand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {"raw_text": "确认撤单第三笔", "quote_content": "1. CO-20260304-4FE9C941"}
        )
        assert result.get("reply_text")
        assert result.get("confirm") is None
        assert result["trace"][0].decision == "close_scope_unresolved"
        backend.assert_not_awaited()

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cc_module)
        result = await close_confirm_cancel(
            {"raw_text": "确认撤单", "quote_content": _QUOTE_TWO}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_confirm_cancel"
        assert "deterministic" in trace[0].decision
        assert "orders=2" in trace[0].decision


# ============================================================
# close.query_status 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseQueryStatusNode:
    async def test_extracts_raw_ids_upper_and_deduped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, qs_module)
        result = await close_query_status(
            {"raw_text": "查询 co-20260305-59772c14 和 CO-20260305-59772C14 状态"}
        )
        assert result["query_filter"]["queryOrderNoList"] == ["CO-20260305-59772C14"]

    async def test_no_ids_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, qs_module)
        result = await close_query_status({"raw_text": "查订单"})
        assert result["query_filter"]["queryOrderNoList"] == []

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, qs_module)
        result = await close_query_status(
            {"raw_text": "查询 CO-20260305-AAAAAAAA CO-20260305-BBBBBBBB CO-20260305-CCCCCCCC"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_query_status"
        assert "deterministic" in trace[0].decision
        assert "orders=3" in trace[0].decision
