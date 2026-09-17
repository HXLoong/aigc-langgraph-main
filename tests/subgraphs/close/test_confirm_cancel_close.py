"""close.confirm_close + close.cancel_close 节点测试（确定性提取，无 LLM）。

行为 1:1 对照原提示词规约：
- 指定范围（raw 单号 / 序号 / 合约编号，并集）→ 仅取指定订单
- 未指定 → 取引用消息全部
- 序号越界 / 合约编号不在引用消息 → 不扩大操作范围，回请求补充
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.close import cancel_close as cancel_module
from app.subgraphs.close import confirm_close as confirm_module
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_close import close_confirm_close

_QUOTE_TWO = (
    "1. CO-20260304-4FE9C941（OPT-SZZSCF20260001）\n"
    "2. CO-20260304-E2BA7501（OPTG-SZZSCF20250030）"
)
_QUOTE_THREE = (
    "期权平仓订单CO-20260304-4FE9C941（OPTG-SZZSCF20250029）：平仓确认下单成功。\n"
    "期权平仓订单CO-20260304-E2BA7501（OPTG-SZZSCF20250030）：平仓确认下单成功。\n"
    "期权平仓订单CO-20260304-3393211B（OPTG-SZZSCF20260003）：平仓确认下单成功。"
)


def _patch(monkeypatch: pytest.MonkeyPatch, module: object) -> AsyncMock:
    """固定后端边界；LLM 工厂若被调用即报错（去 LLM 化硬约束）。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(module, "call_close_backend", backend)

    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    monkeypatch.setattr(module, "get_qwen_thinking", _forbid, raising=False)
    return backend


# ============================================================
# close.confirm_close 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseConfirmCloseNode:
    async def test_raw_order_id_selects_only_that_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {
                "raw_text": "确认平仓 CO-20260304-4FE9C941",
                "quote_content": _QUOTE_TWO,
            }
        )
        assert result["confirm"]["action"] == "close"
        assert result["confirm"]["confirmOrderNoList"] == ["CO-20260304-4FE9C941"]

    async def test_ordinal_resolves_by_quote_position(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {"raw_text": "确认平仓第二笔", "quote_content": _QUOTE_TWO}
        )
        assert result["confirm"]["confirmOrderNoList"] == ["CO-20260304-E2BA7501"]

    async def test_contract_code_maps_to_order_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {
                "raw_text": "确认OPTG-SZZSCF20250029和OPTG-SZZSCF20250030",
                "quote_content": _QUOTE_THREE,
            }
        )
        assert result["confirm"]["confirmOrderNoList"] == [
            "CO-20260304-4FE9C941",
            "CO-20260304-E2BA7501",
        ]

    async def test_unspecified_takes_all_quote_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {"raw_text": "确认平仓", "quote_content": _QUOTE_THREE}
        )
        assert len(result["confirm"]["confirmOrderNoList"]) == 3

    async def test_mixed_ordinal_and_id_union(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """原提示词示例8：确认第一笔和CO-… → 并集。"""
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {
                "raw_text": "确认第一笔和CO-20260304-3393211B",
                "quote_content": _QUOTE_THREE,
            }
        )
        assert result["confirm"]["confirmOrderNoList"] == [
            "CO-20260304-4FE9C941",
            "CO-20260304-3393211B",
        ]

    async def test_no_signals_no_quote_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close({"raw_text": "确认", "quote_content": ""})
        assert result["confirm"]["confirmOrderNoList"] == []

    async def test_unresolved_ordinal_does_not_expand_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """序号越界 → 回请求补充，不调用后端、不扩大到全部订单。"""
        backend = _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {"raw_text": "确认平仓第五笔", "quote_content": "1. CO-20260304-4FE9C941"}
        )
        assert result.get("reply_text")
        assert result.get("confirm") is None
        assert result["trace"][0].decision == "close_scope_unresolved"
        backend.assert_not_awaited()

    async def test_writes_trace_with_order_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, confirm_module)
        result = await close_confirm_close(
            {"raw_text": "确认平仓全部", "quote_content": _QUOTE_THREE}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_confirm_close"
        assert "deterministic" in trace[0].decision
        assert "orders=3" in trace[0].decision


# ============================================================
# close.cancel_close 节点
# ============================================================


@pytest.mark.asyncio
class TestCloseCancelCloseNode:
    async def test_ordinal_selects_first_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {"raw_text": "撤销第一笔", "quote_content": "1. CO-20260304-759125AD"}
        )
        assert result["cancel_params"]["cancelOrderNoList"] == ["CO-20260304-759125AD"]

    async def test_raw_order_id_selects_only_that_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {"raw_text": "撤单 CO-20260304-759125AD", "quote_content": _QUOTE_TWO}
        )
        assert result["cancel_params"]["cancelOrderNoList"] == ["CO-20260304-759125AD"]

    async def test_unspecified_takes_all_quote_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {"raw_text": "都撤了", "quote_content": _QUOTE_TWO}
        )
        assert result["cancel_params"]["cancelOrderNoList"] == [
            "CO-20260304-4FE9C941",
            "CO-20260304-E2BA7501",
        ]

    async def test_conversation_orders_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无引用、无单号时保留历史兜底（取最近一笔会话订单）。"""
        _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {
                "raw_text": "撤",
                "quote_content": "",
                "conversation_orders": [{"orderId": "CO-20260304-ABCD1234"}],
            }
        )
        assert result["cancel_params"]["cancelOrderNoList"] == ["CO-20260304-ABCD1234"]

    async def test_unresolved_scope_does_not_expand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {"raw_text": "撤第五笔", "quote_content": "1. CO-20260304-759125AD"}
        )
        assert result.get("reply_text")
        assert result.get("cancel_params") is None
        assert result["trace"][0].decision == "close_scope_unresolved"
        backend.assert_not_awaited()

    async def test_writes_trace_with_order_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, cancel_module)
        result = await close_cancel_close(
            {"raw_text": "撤销 CO-20260304-AAAAAAAA 和 CO-20260304-BBBBBBBB"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_cancel_close"
        assert "orders=2" in trace[0].decision

    async def test_calls_real_backend_when_context_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P0 payload 对齐：close_order_cancel_request 真后端调用 + 响应逐字节透传。"""
        captured: list[object] = []

        async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
            captured.append(req)
            return {"code": 0, "msg": "ok", "data": "撤单请求已提交"}

        monkeypatch.setattr(
            "app.tools.option_client.OptionClientHttpx.operate",
            _fake_operate,
        )

        def _forbid(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("去 LLM 化节点不应调用 LLM")

        monkeypatch.setattr(
            cancel_module, "get_qwen_thinking", _forbid, raising=False
        )

        result = await close_cancel_close(
            {
                "raw_text": "撤销第一笔",
                "quote_content": "1. CO-20260304-759125AD",
                "conversation_id": "t",
                "user_id": "u",
                "room_id": "r",
                "message_id": 1,
            }
        )
        assert len(captured) == 1
        req = captured[0]
        assert req.type.value == "close_order_cancel_request"
        assert req.close_order_req_vo.model_dump()["cancelOrderNoList"] == [
            "CO-20260304-759125AD"
        ]
        assert result.get("api_result") == "撤单请求已提交"
        assert result.get("api_code") == 0


# ============================================================
# ConversationMemory 回退（ADR 0024 D4）
# ============================================================


@pytest.mark.asyncio
async def test_bare_confirm_close_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """无引用、无指定信号的"确认平仓"读上一轮平仓请求记下的 CO- 单号。"""
    backend = _patch(monkeypatch, confirm_module)
    result = await close_confirm_close({
        "raw_text": "确认平仓", "quote_content": "",
        "conversation_id": "c", "room_id": "r", "user_id": "u", "message_id": 1,
        "last_confirmed_params": {"product_type": "option_close", "order_ids": ["CO-20260304-4FE9C941"]},
    })
    assert result["confirm"]["confirmOrderNoList"] == ["CO-20260304-4FE9C941"]
    backend.assert_awaited_once()


@pytest.mark.asyncio
async def test_specified_but_unresolvable_scope_does_not_use_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户点名了序号 / 合约但引用里对不上 → 仍回请求补充，记忆不得扩大操作范围。"""
    backend = _patch(monkeypatch, confirm_module)
    result = await close_confirm_close({
        "raw_text": "确认平仓 第3笔", "quote_content": "",
        "last_confirmed_params": {"product_type": "option_close", "order_ids": ["CO-20260304-4FE9C941"]},
    })
    assert result["reply_text"] == confirm_module.SCOPE_UNRESOLVED_REPLY
    backend.assert_not_awaited()
