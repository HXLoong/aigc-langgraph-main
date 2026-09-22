"""close 子图路由：编译 + 纯函数路由 + 逐意图真子图路由（原 test_graph / _extended / _p0 已并入本文件）。

- `_route_after_close_intent` 作为纯函数按 `_INTENT_TO_NODE` 参数化，error 优先兜底
- 每个意图在真子图上跑一遍，断言只进入对应节点（含此前从未在真图上跑过的
  close_order_cancel_confirm / close_order_order_query）
- close_todo 占位节点早已删除，不再断言"不存在的节点不在 trace 里"
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import holding_query as hq_module
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.graph import _INTENT_TO_NODE, _route_after_close_intent
from app.subgraphs.close.models import CloseIntentOutput
from tests.intent_fixtures import intent_reply, mock_ainvoke
from tests.llm_guard import forbid_llm
from tests.subgraphs.close.candidate_fixtures import close_candidates, holding_candidates

_CONTEXT = {"conversation_id": "t", "user_id": "u", "room_id": "r", "message_id": 1}
_BUSINESS_NODES = set(_INTENT_TO_NODE.values())


def _patch_close_backend_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """close 链路的真后端调用不打真网络（真联调见 scripts/probe_close_write_e2e.py）。"""

    async def _fake_query_close_orders(self, order_ids=None, contract_codes=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"code": 0, "msg": "ok", "data": []}

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        return {"code": 0, "msg": "ok", "data": "mock-backend-result"}

    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.query_close_orders", _fake_query_close_orders
    )
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", _fake_operate)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, module: object, value: object) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = mock_ainvoke(value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_thinking", lambda: fake_base)


def _patch_intent(monkeypatch: pytest.MonkeyPatch, intent_type: str) -> None:
    _patch_llm(monkeypatch, intent_module, intent_reply(CloseIntentOutput, type=intent_type))


def _state(raw_text: str, **extra: object) -> dict:
    return {**_CONTEXT, "raw_text": raw_text, "message_content": raw_text, **extra}


def _trace_nodes(final: dict) -> list[str]:
    return [e.node for e in final.get("trace", [])]


# ============================================================
# 编译 + 纯函数路由
# ============================================================


def test_close_graph_compiles() -> None:
    assert build_close_graph() is not None


@pytest.mark.parametrize(("intent", "node"), sorted(_INTENT_TO_NODE.items()))
def test_route_after_close_intent_maps_every_intent(intent: str, node: str) -> None:
    assert _route_after_close_intent({"intent": intent}) == node


@pytest.mark.parametrize(
    "state",
    [
        {"intent": "unknown_intent"},
        {},
        {"intent": "close_order_request", "error": object()},
    ],
    ids=["unknown_intent", "missing_intent", "error_wins_over_intent"],
)
def test_route_after_close_intent_falls_back(state: dict) -> None:
    assert _route_after_close_intent(state) == "close_unknown"


# ============================================================
# 逐意图真子图路由：只进对应节点
# ============================================================


@pytest.mark.parametrize(("intent", "node"), sorted(_INTENT_TO_NODE.items()))
async def test_each_intent_enters_only_its_node(
    monkeypatch: pytest.MonkeyPatch, intent: str, node: str
) -> None:
    _patch_intent(monkeypatch, intent)
    _patch_close_backend_calls(monkeypatch)
    _patch_llm(monkeypatch, hq_module, holding_candidates())
    _patch_llm(monkeypatch, pc_module, close_candidates({"orderId": "CO-20260304-AAAA0001"}))

    final = await build_close_graph().ainvoke(
        _state("平仓相关指令 CO-20260304-AAAA0001", quote_content="订单 CO-20260304-AAAA0001")
    )

    entered = set(_trace_nodes(final)) & _BUSINESS_NODES
    assert node in entered, (intent, _trace_nodes(final))
    assert entered - {node} == set(), (intent, entered)
    assert "close_unknown" not in _trace_nodes(final)
    assert final.get("intent") == intent


async def test_unknown_intent_routes_to_close_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_intent(monkeypatch, "unknown_intent")
    final = await build_close_graph().ainvoke(_state("你好啊"))
    nodes = _trace_nodes(final)
    assert "close_intent" in nodes
    assert "close_unknown" in nodes
    assert not (set(nodes) & _BUSINESS_NODES)
    assert final.get("intent") == "unknown_intent"
    unknown_entry = next(e for e in final["trace"] if e.node == "close_unknown")
    assert "unhandled_intent=unknown_intent" in unknown_entry.decision


async def test_close_intent_error_skips_all_business_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """intent 节点失败 → state['error'] → 不进任何业务节点。"""
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
    )
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_llm)
    final = await build_close_graph().ainvoke(_state("x"))
    assert final.get("error") is not None
    assert not (set(_trace_nodes(final)) & _BUSINESS_NODES)


# ============================================================
# 关键节点的业务结果（原 _p0 / _extended 用例）
# ============================================================


async def test_close_query_produces_holding_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_intent(monkeypatch, "close_order_query")
    _patch_llm(monkeypatch, hq_module, holding_candidates())
    monkeypatch.setattr(
        hq_module, "call_close_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )
    final = await build_close_graph().ainvoke(_state("我有哪些期权持仓"))
    assert final.get("close_params") is not None
    assert final["close_params"]["closeable_only"] is False


async def test_close_order_request_reaches_submit_with_order_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "close_order_request")
    _patch_llm(monkeypatch, pc_module, close_candidates({
        "orderId": "CO-20260304-AAAA0001", "closeOrderNotionalDelta": "200万", "closeOrderType": "市价",
    }))
    _patch_close_backend_calls(monkeypatch)
    final = await build_close_graph().ainvoke(_state("平 CO-20260304-AAAA0001 200万 市价"))
    close_params = final.get("close_params") or {}
    assert close_params.get("closeOrderList")
    assert close_params["closeOrderList"][0]["orderId"] == "CO-20260304-AAAA0001"


async def test_confirm_and_cancel_are_deterministic_and_reach_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.subgraphs.close import cancel_close, confirm_close

    forbid_llm(monkeypatch, confirm_close, cancel_close)
    _patch_close_backend_calls(monkeypatch)

    _patch_intent(monkeypatch, "close_order_confirm")
    confirmed = await build_close_graph().ainvoke(
        _state("确认平仓 CO-20260304-ABCD", quote_content="订单 CO-20260304-ABCD")
    )
    assert confirmed.get("confirm", {}).get("action") == "close"

    _patch_intent(monkeypatch, "close_order_cancel_request")
    cancelled = await build_close_graph().ainvoke(_state("撤销平仓单 CO-20260304-A1B2C3D4"))
    assert cancelled.get("cancel_params", {}).get("cancelOrderNoList") == ["CO-20260304-A1B2C3D4"]
