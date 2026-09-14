"""swap 子图编译 + 路由测试（DSL v2 拓扑，原 test_graph.py 已并入本文件）。

覆盖 `app/subgraphs/swap/graph.py` 的**全部路由函数**与端到端链路：

路由函数（纯函数，直接调用）：
- `_route_swap_entry`：text / image / excel 三入口分流
- `_route_after_swap_intent`：6 个真实意图 + unknown 兜底 + cascade
- `_route_after_place_order`：引用消息判空 → 选择链 / 直提提交 / cascade
- `_route_after_select_counterparty` / `_route_after_select_ticker`：顺序推进 + cascade
- `_route_after_multimodal`：图片/Excel 提取后 → 提交 / cascade
- `_has_usable_quote`：quote_content 判空（None / "" / "null" / 空白）

端到端（build_swap_graph().ainvoke，mock LLM + mock backend）：
- place_order_request 无引用 → swap_place_order → submit
- place_order_request 有引用 → swap_place_order → 选择对手 → 选择标的 → submit
- image 入口 → swap_image_order → submit
- unknown_intent → swap_unknown
- intent LLM 抛错 → cascade 到 swap_unknown

测试方法：G3 子图路由/集成（patch LLM + backend，断言 trace 节点序列）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.subgraphs.swap.multimodal as mm_module
import app.subgraphs.swap.select_counterparty as sc_module
import app.subgraphs.swap.select_ticker as st_module
from app.graph.state import TickerCandidate
from app.subgraphs.swap import backend as swap_backend_module
from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.graph import (
    _has_usable_quote,
    _route_after_multimodal,
    _route_after_place_order,
    _route_after_select_counterparty,
    _route_after_select_ticker,
    _route_after_swap_intent,
    _route_swap_entry,
)
from app.subgraphs.swap.models import (
    SwapCounterpartyPick,
    SwapIntentOutput,
    SwapOrderItem,
    SwapPlaceOrderParams,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
    SwapTickerPick,
)
from app.subgraphs.ticker.resolver import TickerResolution


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[TickerCandidate],
) -> None:
    resolution = TickerResolution(resolved=candidates, hitl_pending=[])
    monkeypatch.setattr(po_module, "resolve_ticker_full", AsyncMock(return_value=resolution))


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    value: object,
    fn: str = "get_qwen_thinking",
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, fn, lambda: fake_base)
    return fake_llm.ainvoke


def _patch_backend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(return_value=MagicMock(code=0, data={}, msg=""))
    monkeypatch.setattr(swap_backend_module, "SwapClientHttpx", lambda: fake_client)
    return fake_client


def _patch_vl_and_extract(
    monkeypatch: pytest.MonkeyPatch, params: SwapPlaceOrderParams
) -> None:
    ocr_llm = MagicMock()
    ocr_llm.ainvoke = AsyncMock(return_value=MagicMock(content="OCR 文本"))
    monkeypatch.setattr(mm_module, "get_qwen_vl", lambda: ocr_llm)

    extract_llm = MagicMock()
    extract_llm.ainvoke = AsyncMock(return_value=params)
    factory = MagicMock()
    factory.with_structured_output = MagicMock(return_value=extract_llm)
    monkeypatch.setattr(mm_module, "get_qwen_structured", lambda: factory)


_BASE_STATE: dict = {
    "raw_text": "互换下单 腾讯 1000 股",
    "conversation_id": "t",
    "user_id": "u",
    "room_id": "r",
    "message_id": 1,
    "message_content": "x",
}


# ============================================================
# 编译冒烟
# ============================================================


def test_swap_graph_compiles() -> None:
    """子图能编译，不抛异常。"""
    graph = build_swap_graph()
    assert graph is not None


# ============================================================
# _has_usable_quote（互换-引用消息判空）
# ============================================================


class TestHasUsableQuote:
    def test_none(self) -> None:
        assert _has_usable_quote({}) is False

    def test_empty_string(self) -> None:
        assert _has_usable_quote({"quote_content": ""}) is False

    def test_null_literal_case_insensitive(self) -> None:
        assert _has_usable_quote({"quote_content": "null"}) is False
        assert _has_usable_quote({"quote_content": "NULL"}) is False
        assert _has_usable_quote({"quote_content": "  Null  "}) is False

    def test_real_quote_is_usable(self) -> None:
        assert _has_usable_quote({"quote_content": "订单H-1（序号1）："}) is True

    def test_whitespace_only_is_usable(self) -> None:
        """仅空白也算「非空」（与 Dify 原判断一致：只排除空/null）。"""
        assert _has_usable_quote({"quote_content": "   "}) is True


# ============================================================
# _route_swap_entry（text / image / excel 三入口）
# ============================================================


class TestRouteSwapEntry:
    def test_default_is_text(self) -> None:
        assert _route_swap_entry({}) == "swap_intent"

    def test_explicit_text(self) -> None:
        assert _route_swap_entry({"swap_input_mode": "text"}) == "swap_intent"

    def test_image_mode(self) -> None:
        assert _route_swap_entry({"swap_input_mode": "image"}) == "swap_image_order"

    def test_excel_mode(self) -> None:
        assert _route_swap_entry({"swap_input_mode": "excel"}) == "swap_excel_order"


# ============================================================
# _route_after_swap_intent（6 意图 + 兜底 + cascade）
# ============================================================


class TestRouteAfterSwapIntent:
    @pytest.mark.parametrize(
        ("intent", "expected"),
        [
            ("place_order_request", "swap_place_order"),
            ("cancel_order_request", "swap_cancel"),
            ("confirm_order", "swap_confirm"),
            ("confirm_cancel_order", "swap_confirm"),
            ("confirm_modify_order", "swap_confirm"),
            ("query_order_status", "swap_query_order"),
            ("unknown_intent", "swap_unknown"),
        ],
    )
    def test_all_intents_route_to_expected_node(self, intent: str, expected: str) -> None:
        assert _route_after_swap_intent({"intent": intent}) == expected

    def test_missing_intent_falls_back_to_unknown(self) -> None:
        assert _route_after_swap_intent({}) == "swap_unknown"

    def test_error_takes_priority(self) -> None:
        """cascade 防御优先于意图分发。"""
        state = {"intent": "place_order_request", "error": MagicMock()}
        assert _route_after_swap_intent(state) == "swap_unknown"


# ============================================================
# _route_after_place_order（引用判空 → 选择链 / 提交）
# ============================================================


class TestRouteAfterPlaceOrder:
    def test_usable_quote_goes_to_counterparty(self) -> None:
        state = {"quote_content": "订单H-1（序号1）："}
        assert _route_after_place_order(state) == "swap_select_counterparty"

    def test_no_quote_goes_straight_to_submit(self) -> None:
        assert _route_after_place_order({}) == "swap_place_order_submit"

    def test_null_quote_goes_straight_to_submit(self) -> None:
        assert _route_after_place_order({"quote_content": "null"}) == "swap_place_order_submit"

    def test_error_goes_to_unknown(self) -> None:
        state = {"quote_content": "订单H-1", "error": MagicMock()}
        assert _route_after_place_order(state) == "swap_unknown"


# ============================================================
# 选择链 / 多模态后的路由
# ============================================================


class TestRouteAfterSelectChain:
    def test_after_counterparty_goes_to_ticker(self) -> None:
        assert _route_after_select_counterparty({}) == "swap_select_ticker"

    def test_after_counterparty_error(self) -> None:
        assert _route_after_select_counterparty({"error": MagicMock()}) == "swap_unknown"

    def test_after_ticker_goes_to_submit(self) -> None:
        assert _route_after_select_ticker({}) == "swap_place_order_submit"

    def test_after_ticker_error(self) -> None:
        assert _route_after_select_ticker({"error": MagicMock()}) == "swap_unknown"

    def test_after_multimodal_goes_to_submit(self) -> None:
        assert _route_after_multimodal({}) == "swap_place_order_submit"

    def test_after_multimodal_error(self) -> None:
        assert _route_after_multimodal({"error": MagicMock()}) == "swap_unknown"


# ============================================================
# 端到端（mock LLM + mock backend）
# ============================================================


class TestSwapGraphEndToEnd:
    @pytest.mark.asyncio
    async def test_place_order_request_without_quote_runs_place_then_submit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无引用消息 → swap_place_order → submit（跳过选择链）。"""
        _patch_resolver(
            monkeypatch,
            [TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True)],
        )
        _patch(monkeypatch, intent_module, SwapIntentOutput(type="place_order_request"))
        _patch(
            monkeypatch,
            po_module,
            SwapPlaceOrderParams(
                orderList=[SwapOrderItem(placeOrderWindCode="腾讯", placeOrderQuantity=1000)]
            ),
            fn="get_qwen_complex",
        )
        _patch_backend(monkeypatch)

        graph = build_swap_graph()
        final = await graph.ainvoke(dict(_BASE_STATE))

        trace_nodes = [e.node for e in final.get("trace", [])]
        assert trace_nodes == ["swap_intent", "swap_place_order", "swap_place_order_submit"]
        assert final.get("intent") == "place_order_request"
        assert final.get("place_params", {}).get("expected_action") == "place"
        assert "swap_todo" not in trace_nodes
        # ticker 集成验证
        tickers = final.get("tickers", [])
        assert any("700" in t.wind_code and t.wind_code.endswith(".HK") for t in tickers)
        assert all(t.from_goats for t in tickers)

    @pytest.mark.asyncio
    async def test_place_order_request_with_quote_runs_full_select_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """有引用消息 → place_order → select_counterparty → select_ticker → submit。"""
        _patch_resolver(monkeypatch, [])
        _patch(monkeypatch, intent_module, SwapIntentOutput(type="place_order_request"))
        _patch(
            monkeypatch,
            po_module,
            SwapPlaceOrderParams(
                orderList=[
                    SwapOrderItem(
                        orderId="H-1", placeOrderWindCode="腾讯", placeOrderQuantity=1000
                    )
                ]
            ),
            fn="get_qwen_complex",
        )
        _patch(
            monkeypatch,
            sc_module,
            SwapSelectCounterpartyOutput(
                hasSignal=True, picks=[SwapCounterpartyPick(orderId="H-1", letter="A")]
            ),
            fn="get_qwen_complex",
        )
        _patch(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", seq=2)]),
            fn="get_qwen_complex",
        )
        _patch_backend(monkeypatch)

        graph = build_swap_graph()
        final = await graph.ainvoke(
            {
                **_BASE_STATE,
                "quote_content": "订单H-1（序号1）：",
                "swap_counterparties": [{"shortName": "临沂阿凡提", "sort": "A"}],
                "quote_ticker_candidates": [
                    {
                        "orderId": "H-1",
                        "candidates": [
                            {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
                            {"seq": 2, "code": "00700.HK", "name": "腾讯控股"},
                        ],
                    }
                ],
            }
        )

        trace_nodes = [e.node for e in final.get("trace", [])]
        assert trace_nodes == [
            "swap_intent",
            "swap_place_order",
            "swap_select_counterparty",
            "swap_select_ticker",
            "swap_place_order_submit",
        ]
        order = final["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "临沂阿凡提"
        assert order["placeOrderWindCode"] == "00700.HK"

    @pytest.mark.asyncio
    async def test_image_input_mode_runs_multimodal_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """swap_input_mode=image → swap_image_order → submit（跳过意图识别）。"""
        _patch_vl_and_extract(
            monkeypatch,
            SwapPlaceOrderParams(
                orderList=[SwapOrderItem(placeOrderWindCode="600519.SH", placeOrderQuantity=100)]
            ),
        )
        _patch_backend(monkeypatch)

        graph = build_swap_graph()
        final = await graph.ainvoke(
            {
                **_BASE_STATE,
                "swap_input_mode": "image",
                "input_files": [{"type": "image", "url": "http://i/1.png"}],
            }
        )

        trace_nodes = [e.node for e in final.get("trace", [])]
        assert trace_nodes == ["swap_image_order", "swap_place_order_submit"]
        assert final["place_params"]["orderList"][0]["placeOrderWindCode"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_unknown_intent_routes_to_swap_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, intent_module, SwapIntentOutput(type="unknown_intent"))

        graph = build_swap_graph()
        final = await graph.ainvoke({**_BASE_STATE, "raw_text": "你好啊"})

        trace_nodes = [e.node for e in final.get("trace", [])]
        assert "swap_intent" in trace_nodes
        assert "swap_unknown" in trace_nodes
        assert "swap_place_order" not in trace_nodes
        unknown_entry = next(e for e in final["trace"] if e.node == "swap_unknown")
        assert "unhandled_intent=unknown_intent" in unknown_entry.decision

    @pytest.mark.asyncio
    async def test_intent_error_routes_to_swap_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cascade 防御：intent LLM 抛错 → swap_unknown（不 cascade 到下游）。"""
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(
            return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
        )
        monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_base)

        graph = build_swap_graph()
        final = await graph.ainvoke(dict(_BASE_STATE))

        assert final.get("error") is not None
        trace_nodes = [e.node for e in final.get("trace", [])]
        assert "swap_unknown" in trace_nodes
        for unexpected in (
            "swap_place_order",
            "swap_confirm",
            "swap_cancel",
            "swap_query_order",
        ):
            assert unexpected not in trace_nodes
