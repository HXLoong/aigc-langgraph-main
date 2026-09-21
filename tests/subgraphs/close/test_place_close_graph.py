"""close.place_close 子图（ADR 0024 重构 5）：6 阶段厚节点变真图，每阶段可归因。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.place_close import build_place_close_graph, close_place_close
from tests.subgraphs.close.candidate_fixtures import close_candidates

STAGES = (
    "place_close_parse",
    "place_close_fetch_orders",
    "place_close_extract",
    "place_close_normalize",
    "place_close_validate",
    "place_close_submit",
    "place_close_reject",
)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, params: BaseModel) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(pc_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


def _patch_query(monkeypatch: pytest.MonkeyPatch, holdings: list[dict[str, Any]]) -> None:
    async def _fake_query(self, order_ids=None, contract_codes=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"code": 0, "msg": "ok", "data": holdings}

    monkeypatch.setattr(
        "app.subgraphs.close.place_close.OptionClientHttpx.query_close_orders", _fake_query
    )


def _patch_operate(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    captured = MagicMock()

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        captured(req)
        return {"code": 0, "msg": "ok", "data": "backend-card"}

    monkeypatch.setattr("app.subgraphs.close.place_close.OptionClientHttpx.operate", _fake_operate)
    return captured


def _ctx(raw_text: str) -> dict[str, Any]:
    return {"raw_text": raw_text, "conversation_id": "t", "user_id": "u", "room_id": "r",
            "message_id": 1}


def test_place_close_graph_topology_and_output_schema() -> None:
    graph = build_place_close_graph()
    assert isinstance(graph, CompiledStateGraph)
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert set(STAGES) <= nodes
    out = set(graph.output_channels)
    assert {"close_params", "reply_text", "intent", "api_result", "api_code", "trace", "error"} <= out
    assert not ({"product_type", "swap_input_mode", "history_messages", "raw_text"} & out)
    # 私有中间态不外泄
    assert not any(ch.startswith("pc_") for ch in out)


@pytest.mark.asyncio
async def test_happy_path_traces_every_stage_and_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "CO-20260304-AAAA0001", "closeOrderNotionalDelta": "200万",
                      "closeOrderType": "市价"}))
    result = await close_place_close(_ctx("平 CO-20260304-AAAA0001 200万 市价"))

    assert result.get("error") is None
    nodes = [e.node for e in result["trace"]]
    for stage in ("place_close_parse", "place_close_fetch_orders", "place_close_extract",
                  "place_close_normalize", "place_close_validate", "place_close_submit"):
        assert stage in nodes, nodes
    assert "place_close_reject" not in nodes
    # 汇总条目保留原节点名，兼容按 close_place_close 归因的看板 / 测试
    summary = [e for e in result["trace"] if e.node == "close_place_close"]
    assert len(summary) == 1 and "orders=1" in summary[0].decision
    assert result["api_result"] == "backend-card"
    assert result["intent"] == "close_order_request"
    captured.assert_called_once()


@pytest.mark.asyncio
async def test_relative_twap_duration_requires_explicit_time_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({
        "orderId": "CO-20260304-AAAA0001", "closeOrderNotionalDelta": "200万",
        "closeOrderType": "TWAP", "closeOrderPrice": "10",
    }))
    result = await close_place_close(_ctx("CO-20260304-AAAA0001，200万，TWAP30分钟，限价10"))

    assert "TWAP" in result["reply_text"] and "起止时间" in result["reply_text"]
    assert "CO-20260304-AAAA0001" in result["reply_text"]
    assert "place_close_reject" in [entry.node for entry in result["trace"]]
    captured.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("combined", [False, True])
async def test_explicit_twap_time_range_reaches_backend(monkeypatch: pytest.MonkeyPatch, combined: bool) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({
        "orderId": "CO-20260304-AAAA0001", "closeOrderNotionalDelta": "200万",
        "closeOrderType": "TWAP13:00-13:30" if combined else "TWAP", "closeOrderPrice": "10",
        "closeOrderAlgoStartTime": None if combined else "13:00",
        "closeOrderAlgoEndTime": None if combined else "13:30",
    }))
    result = await close_place_close(_ctx("CO-20260304-AAAA0001，200万，TWAP13:00-13:30，限价10"))

    assert not result.get("error")
    captured.assert_called_once()
    item = captured.call_args.args[0].close_order_req_vo.model_extra["closeOrderList"][0]
    assert item["closeOrderAlgoStartTime"] == "13:00"
    assert item["closeOrderAlgoEndTime"] == "13:30"


@pytest.mark.asyncio
@pytest.mark.parametrize("ratio", [None, "9", "POV9"])
async def test_compound_pov_candidate_keeps_ratio_and_evidence(monkeypatch: pytest.MonkeyPatch, ratio: str | None) -> None:
    order = "CO-20260304-AAAA0001"
    quote = f"序号：1\n合约编号：OPT-TEST1\n单号：{order}\n平仓价格方式：【待补充】"
    _patch_query(monkeypatch, [{"orderId": order, "contractCode": "OPT-TEST1"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({
        "orderId": {"value": order, "evidence": order, "origin": "quote", "confidence": 1.0},
        "closeOrderType": "POV9", "closeOrderPovRatio": ratio,
    }))
    result = await close_place_close({**_ctx("POV9"), "quote_content": quote})
    assert not result.get("error"), result.get("error")
    captured.assert_called_once()
    row = captured.call_args.args[0].close_order_req_vo.model_extra["closeOrderList"][0]
    assert row["closeOrderType"] == "POV" and row["closeOrderPovRatio"] == 9
    record = result["field_records"]["close/place_close.orderList.0.closeOrderPovRatio"]
    assert record.evidence == (ratio or "POV9") and record.value == 9


@pytest.mark.asyncio
async def test_compound_twap_duration_still_requires_time_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({
        "orderId": "CO-20260304-AAAA0001", "closeOrderType": "TWAP30分钟",
    }))
    result = await close_place_close(_ctx("CO-20260304-AAAA0001 TWAP30分钟"))
    assert not result.get("error")
    assert "起止时间" in result["reply_text"]
    captured.assert_not_called()


@pytest.mark.asyncio
async def test_compound_negated_pov_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({
        "orderId": "CO-20260304-AAAA0001", "closeOrderType": "POV9",
    }))
    result = await close_place_close(_ctx("CO-20260304-AAAA0001 不要POV9"))
    assert result.get("error")
    captured.assert_not_called()


@pytest.mark.asyncio
async def test_empty_merge_takes_reject_edge_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates())
    result = await close_place_close(_ctx("x"))
    nodes = [e.node for e in result["trace"]]
    assert "place_close_reject" in nodes and "place_close_submit" not in nodes
    assert "place_close_validate" not in nodes  # 空列表在 normalize 后直接走 reject 边
    assert result["reply_text"] == "未能识别平仓参数，请提供订单号或持仓序号。"
    assert result["close_params"]["closeOrderList"] == []
    captured.assert_not_called()


@pytest.mark.asyncio
async def test_validation_failure_takes_reject_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "CO-20260304-AAAA0001", "closeOrderType": "限价"}))
    result = await close_place_close(_ctx("平 CO-20260304-AAAA0001 限价"))
    nodes = [e.node for e in result["trace"]]
    assert "place_close_validate" in nodes and "place_close_reject" in nodes
    assert "place_close_submit" not in nodes
    assert result["reply_text"].startswith("参数校验不通过")
    captured.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_is_attributed_to_extract_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query(monkeypatch, [])
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
    )
    monkeypatch.setattr(pc_module, "get_qwen_thinking", lambda: fake_base)
    result = await close_place_close(_ctx("平 CO-1"))
    assert result["error"].node == "place_close_extract"
    nodes = [e.node for e in result["trace"]]
    # 出错后不再执行下游阶段（cascade 防御在子图内生效）
    assert "place_close_normalize" not in nodes and "place_close_submit" not in nodes
