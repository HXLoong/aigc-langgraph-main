"""编译后互换子图：只 mock LLM、文件下载和后端 HTTP 边界。"""
from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openpyxl
import pytest

from app.graph.state import AgentState
from app.subgraphs.swap import (
    backend,
    build_swap_graph,
    intent,
    multimodal,
    place_order,
    select_counterparty,
    select_ticker,
)
from app.subgraphs.swap.models import (
    SwapIntentOutput,
    SwapOrderItem,
    SwapPlaceOrderParams,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
)
from app.tools.swap_client import SwapClientHttpx
from tests.evidence_support import candidate_output, swap_candidate_output
from tests.intent_fixtures import intent_reply, mock_ainvoke
from tests.subgraphs.swap.test_fresh_counterparty import fresh_state, patch_recognition


def patch_structured(
    monkeypatch: pytest.MonkeyPatch, module: Any, factory: str, output: Any,
) -> AsyncMock:
    invoke = mock_ainvoke(swap_candidate_output(output) if module is place_order and isinstance(output, SwapPlaceOrderParams) else output)
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(module, factory, lambda: model)
    return invoke


def graph_boundaries(
    monkeypatch: pytest.MonkeyPatch, params: SwapPlaceOrderParams,
    *, ticker_rows: list[dict[str, Any]] | None = None,
) -> tuple[AgentState, list[dict[str, Any]]]:
    patch_structured(monkeypatch, intent, "get_qwen_thinking",
                     intent_reply(SwapIntentOutput, type="place_order_request"))
    patch_structured(monkeypatch, place_order, "get_qwen_complex", params)
    requests: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin-api/integration/securities-instrument/select":
            return httpx.Response(200, json={"code": 0, "data": ticker_rows or []})
        assert request.url.path == "/admin-api/swap-order/operate"
        assert request.method == "POST"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "后端原始回复"})

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://swap.test", token="test-only", transport=transport, dry_run=False,
    ))
    state: AgentState = {
        **fresh_state(), "conversation_id": "fresh-test", "message_id": 12345,
        "user_id": "test-user", "room_id": "test-room", "product_type": "swap",
    }
    state.pop("place_params")
    return state, requests


@pytest.mark.parametrize("quote", [None, "", "null", " NuLL "])
async def test_fresh_all_holdings_reaches_backend_with_completed_counterparty(
    monkeypatch: pytest.MonkeyPatch, quote: str | None,
) -> None:
    params = SwapPlaceOrderParams(orderList=[SwapOrderItem(
        placeOrderCloseIntent=True, placeOrderEntrustRatio=1,
    )])
    state, requests = graph_boundaries(monkeypatch, params)
    state["quote_content"] = quote
    candidates = candidate_output(params, spellings={"True": "平仓", "1": "全部持仓"})
    candidates.order_list[0].place_order_entrust_ratio.evidence = state["raw_text"]
    patch_structured(monkeypatch, place_order, "get_qwen_complex", candidates)
    patch_recognition(monkeypatch, {"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "价值精选"},
    ]})

    final = await build_swap_graph().ainvoke(state)

    assert not final.get("error"), final.get("error")
    assert len(requests) == 1
    request = requests[0]
    order = request["orderList"][0]
    assert order["placeOrderShortname"] == "聚鸣价值精选"
    assert order.get("placeOrderOrderDirection") is None
    assert order["placeOrderCloseIntent"] is True
    assert order["placeOrderEntrustRatio"] == 1
    # 子图 output_schema 只回传写回面（ADR 0024 D2），入口字段以传入 state 为准
    assert request["rawContent"] == state["raw_text"] == "平仓价值精选全部持仓"
    # 既有后端上下文协议会把非空 quote（包括字面量 null）追加到 messageContent。
    assert request["messageContent"] == "平仓价值精选全部持仓" + (f"\n{quote}" if quote else "")
    assert [entry.node for entry in final["trace"] if entry.node not in {"swap_extract_candidates", "swap_normalize", "swap_place_result"}] == [
        "swap_intent", "swap_place_order", "swap_recognize_fresh_counterparty",
        "swap_place_order_submit",
    ]


async def test_current_dev_case_7_broadcasts_name_to_both_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures/biz/swap_prod_acceptance.jsonl"
    original_fixture = fixture.read_bytes()
    case = next(json.loads(line) for line in original_fixture.decode("utf-8").splitlines()
                if line.strip() and json.loads(line).get("caseNo")
                == "ai_trade_assist_prod_accept_order_dev_case_7")
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(
            placeOrderWindCode="300748.SZ", placeOrderQuantity=30000,
            placeOrderOrderDirection="SELL",
            placeOrderPrice=24.6, placeOrderPremarket=True,
        ),
        SwapOrderItem(
            placeOrderWindCode="300748.SZ", placeOrderQuantity=50000,
            placeOrderOrderDirection="SELL", hasFastExecutionIntent=True,

        ),
    ])
    original_params = deepcopy(params.model_dump())
    state, requests = graph_boundaries(monkeypatch, params)
    state["raw_text"] = case["send_text"]
    extracted = candidate_output(params, spellings={"300748.SZ": "300748.sz", "30000": "3万股", "50000": "5万股", "SELL": "卖出"})
    extracted.order_list[0].place_order_premarket.value = "集合竞价"
    extracted.order_list[0].place_order_premarket.evidence = "集合竞价"
    extracted.order_list[1].has_fast_execution_intent.value = "尽快"
    extracted.order_list[1].has_fast_execution_intent.evidence = "尽快"
    patch_structured(monkeypatch, place_order, "get_qwen_complex", extracted)
    patch_recognition(monkeypatch, {"hasSignal": True, "matches": [
        {"shortName": "聚鸣价值精选", "evidence": "聚鸣价值精选"},
    ]})

    final = await build_swap_graph().ainvoke(state)

    assert not final.get("error"), final.get("error")
    assert len(requests) == 1
    orders = requests[0]["orderList"]
    assert [order["placeOrderShortname"] for order in orders] == ["聚鸣价值精选"] * 2
    assert [order["placeOrderWindCode"] for order in orders] == ["300748.sz"] * 2
    assert [order["placeOrderQuantity"] for order in orders] == [30000, 50000]
    assert [order["placeOrderOrderDirection"] for order in orders] == ["SELL"] * 2
    assert orders[0]["placeOrderPrice"] == "24.6"
    assert orders[0]["placeOrderPremarket"] is True
    assert orders[1]["hasFastExecutionIntent"] is True
    assert orders[1].get("placeOrderAlgorithmType") is None
    assert orders[1].get("placeOrderPovPercent") is None
    assert requests[0]["rawContent"] == requests[0]["messageContent"] == case["send_text"]
    trace = next(e for e in final["trace"] if e.node == "swap_recognize_fresh_counterparty")
    assert trace.llm_output["affected_orders"] == [0, 1]
    assert params.model_dump() == original_params
    assert fixture.read_bytes() == original_fixture


@pytest.mark.parametrize("failure", ["request", "structured"])
async def test_fresh_recognition_failure_stops_submission_and_reaches_fallback(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    state, requests = graph_boundaries(monkeypatch, SwapPlaceOrderParams(orderList=[SwapOrderItem()]))
    invoke = patch_recognition(monkeypatch, {"hasSignal": True})  # missing required matches
    if failure == "request":
        invoke.side_effect = RuntimeError("model unavailable")

    final = await build_swap_graph().ainvoke(state)

    assert requests == []
    assert final["error"].node == "swap_recognize_fresh_counterparty"
    assert final["error"].type == ("RuntimeError" if failure == "request" else "ValidationError")
    trace_nodes = [entry.node for entry in final["trace"]]
    assert trace_nodes[-2:] == ["swap_recognize_fresh_counterparty", "swap_unknown"]
    if failure == "structured":
        assert final["trace"][-2].decision == "error:retry_exhausted"
    assert "swap_place_order_submit" not in trace_nodes


@pytest.mark.parametrize("mode", ["quote", "image", "excel"])
async def test_reference_and_multimodal_paths_do_not_call_fresh_recognition(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    params = SwapPlaceOrderParams(orderList=[SwapOrderItem(placeOrderShortname="原有对手", placeOrderWindCode="NVDA.O")])
    state, requests = graph_boundaries(monkeypatch, params, ticker_rows=[{"windCode": "NVDA.O", "insShtDesc": "英伟达"}])
    state["swap_counterparties"] = [{"shortName": "原有对手", "sort": "A"}]
    invoke = patch_recognition(monkeypatch, {})
    invoke.side_effect = AssertionError("this path must not call fresh recognition")
    if mode == "quote":
        state["raw_text"] = "保持原有对手 NVDA.O"
        state["quote_content"] = "引用订单 H-20260914-1234567890"
        patch_structured(monkeypatch, select_counterparty, "get_qwen_complex",
                         SwapSelectCounterpartyOutput(hasSignal=False))
        patch_structured(monkeypatch, select_ticker, "get_qwen_complex", SwapSelectTickerOutput())
    else:
        state["swap_input_mode"] = mode
        state["input_files"] = [{"type": mode, "url": "https://files.test/orders"}]
        reference = "file:0:image" if mode == "image" else "file:0:sheet:0:row:2"
        candidates = candidate_output(params, origin="attachment")
        for row in candidates.order_list:
            for name in type(row).model_fields:
                candidate = getattr(row, name)
                if candidate is not None:
                    candidate.reference = reference
        patch_structured(monkeypatch, multimodal, "get_qwen_structured", candidates)
        if mode == "image":
            vl = MagicMock()
            vl.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"text": "原有对手 NVDA.O"})
            monkeypatch.setattr(multimodal, "get_qwen_vl", lambda: vl)
        else:
            workbook = openpyxl.Workbook()
            workbook.active.append(["产品", "标的"])
            workbook.active.append(["原有对手", "NVDA.O"])
            stream = io.BytesIO()
            workbook.save(stream)
            # 下载边界被模拟，Excel 解析仍运行真实实现。
            monkeypatch.setattr(multimodal, "_fetch_bytes", AsyncMock(return_value=stream.getvalue()))

    final = await build_swap_graph().ainvoke(state)

    assert not final.get("error"), final.get("error")
    assert len(requests) == 1
    assert requests[0]["orderList"][0]["placeOrderShortname"] == "原有对手"
    invoke.assert_not_awaited()
    assert "swap_recognize_fresh_counterparty" not in [entry.node for entry in final["trace"]]
