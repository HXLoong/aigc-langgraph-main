"""swap.select_counterparty / swap.select_ticker 节点测试（DSL v2 新节点）。

覆盖：
- `app/subgraphs/swap/select_counterparty.py::swap_select_counterparty`
  （互换-选择交易对手：LLM-B 指针 → 确定性查表覆盖 placeOrderShortname）
- `app/subgraphs/swap/select_ticker.py::swap_select_ticker`
  （互换-选择标的：LLM-A 指针 → 确定性查表覆盖 placeOrderWindCode）

两者共同约定（见各自模块 docstring）：
- 只覆盖**非空**解析结果，非破坏性——解析空/无信号时保留 swap.place_order 原值
- `candidate_list` 为空时 select_ticker **跳过 LLM 调用**（Dify 原节点语义）
- `@safe_node` 兜底：LLM 异常 → state['error']

测试方法：G2 节点单测（mock LLM 工厂，patch 打在**使用点**模块）。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.subgraphs.swap.select_counterparty as sc_module
import app.subgraphs.swap.select_ticker as st_module
from app.subgraphs.swap.models import (
    SwapCounterpartyPick,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
    SwapTickerPick,
)
from app.subgraphs.swap.select_counterparty import (
    _build_user_message as sc_build_user_message,
)
from app.subgraphs.swap.select_counterparty import (
    _format_shortname_list,
    swap_select_counterparty,
)
from app.subgraphs.swap.select_ticker import _build_user_message as st_build_user_message
from app.subgraphs.swap.select_ticker import swap_select_ticker

# ============================================================
# 夹具
# ============================================================

_TRS: list[dict] = [
    {"ctptyId": "1", "shortName": "临沂阿凡提", "longName": "临沂阿凡提有限公司", "sort": "A"},
    {"ctptyId": "2", "shortName": "测试111", "longName": "测试有限公司", "sort": "B"},
]

_CANDIDATES: list[dict] = [
    {
        "orderId": "H-1",
        "orderSeq": 1,
        "candidates": [
            {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
            {"seq": 2, "code": "00700.HK", "name": "腾讯控股"},
        ],
    }
]


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, module: object, output: object
) -> AsyncMock:
    """patch 使用点模块的 get_qwen_complex（测试规范：patch where it's looked up）。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=output)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_complex", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# _format_shortname_list / _build_user_message
# ============================================================


class TestFormatShortnameList:
    def test_empty_and_none(self) -> None:
        assert _format_shortname_list(None) == ""
        assert _format_shortname_list([]) == ""

    def test_sort_colon_shortname_joined(self) -> None:
        assert _format_shortname_list(_TRS) == "A:临沂阿凡提, B:测试111"

    def test_missing_fields_tolerated(self) -> None:
        assert _format_shortname_list([{"shortName": "X"}]) == ":X"


class TestBuildUserMessages:
    def test_counterparty_message_has_three_sections(self) -> None:
        msg = sc_build_user_message(
            {
                "raw_text": "选B",
                "quote_content": "单号：H-1",
                "swap_counterparties": _TRS,
            }
        )
        assert "raw_content：选B" in msg
        assert "shortname_list：A:临沂阿凡提, B:测试111" in msg
        assert "quote_content：单号：H-1" in msg

    def test_counterparty_message_handles_empty_state(self) -> None:
        msg = sc_build_user_message({})
        assert "raw_content：" in msg
        assert "shortname_list：" in msg
        assert "quote_content：" in msg

    def test_ticker_message_embeds_candidate_json(self) -> None:
        msg = st_build_user_message(
            {
                "raw_text": "换成腾讯",
                "quote_content": "单号：H-1",
                "quote_ticker_candidates": _CANDIDATES,
            }
        )
        assert "raw_content：换成腾讯" in msg
        assert "quote_content：单号：H-1" in msg
        assert json.dumps(_CANDIDATES, ensure_ascii=False) in msg

    def test_ticker_message_handles_empty_state(self) -> None:
        msg = st_build_user_message({})
        assert "candidate_list：[]" in msg


# ============================================================
# swap_select_counterparty
# ============================================================


def _sc_state(**overrides: object) -> dict:
    state: dict = {
        "raw_text": "选B",
        "quote_content": "单号：H-1",
        "swap_counterparties": _TRS,
        "place_params": {
            "expected_action": "place",
            "orderList": [{"orderId": "H-1", "placeOrderShortname": "旧对手"}],
        },
    }
    state.update(overrides)
    return state


class TestSwapSelectCounterpartyNode:
    @pytest.mark.asyncio
    async def test_letter_pick_overwrites_shortname(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            sc_module,
            SwapSelectCounterpartyOutput(
                hasSignal=True, picks=[SwapCounterpartyPick(orderId="H-1", letter="B")]
            ),
        )
        out = await swap_select_counterparty(_sc_state())
        assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "测试111"
        assert out["place_params"]["expected_action"] == "place"

    @pytest.mark.asyncio
    async def test_direct_name_pick_overwrites(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            sc_module,
            SwapSelectCounterpartyOutput(
                hasSignal=True,
                picks=[SwapCounterpartyPick(orderId="H-1", directName="临沂阿凡提")],
            ),
        )
        out = await swap_select_counterparty(_sc_state())
        assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "临沂阿凡提"

    @pytest.mark.asyncio
    async def test_no_signal_keeps_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, sc_module, SwapSelectCounterpartyOutput(hasSignal=False))
        out = await swap_select_counterparty(_sc_state())
        assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "旧对手"

    @pytest.mark.asyncio
    async def test_signal_with_empty_picks_keeps_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch, sc_module, SwapSelectCounterpartyOutput(hasSignal=True, picks=[])
        )
        out = await swap_select_counterparty(_sc_state())
        assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "旧对手"

    @pytest.mark.asyncio
    async def test_unresolvable_pick_keeps_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指针解析不到对手 → 非破坏性保留原值。"""
        _patch_llm(
            monkeypatch,
            sc_module,
            SwapSelectCounterpartyOutput(
                hasSignal=True, picks=[SwapCounterpartyPick(orderId="H-1", letter="Z")]
            ),
        )
        out = await swap_select_counterparty(_sc_state())
        assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "旧对手"

    @pytest.mark.asyncio
    async def test_trace_records_signal_and_pick_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            sc_module,
            SwapSelectCounterpartyOutput(
                hasSignal=True, picks=[SwapCounterpartyPick(letter="A")]
            ),
        )
        out = await swap_select_counterparty(_sc_state())
        trace = out["trace"]
        assert len(trace) == 1
        assert trace[0].node == "swap_select_counterparty"
        assert trace[0].decision == "hasSignal=True,picks=1"
        assert trace[0].llm_output is not None

    @pytest.mark.asyncio
    async def test_missing_place_params_defaults_to_empty_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, sc_module, SwapSelectCounterpartyOutput(hasSignal=False))
        out = await swap_select_counterparty({"raw_text": "x"})
        assert out["place_params"] == {"expected_action": "", "orderList": []}

    @pytest.mark.asyncio
    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(
            return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
        )
        monkeypatch.setattr(sc_module, "get_qwen_complex", lambda: fake_base)
        out = await swap_select_counterparty(_sc_state())
        assert out["error"] is not None
        assert out["error"].node == "swap_select_counterparty"
        assert "LLM down" in out["error"].message


# ============================================================
# swap_select_ticker
# ============================================================


def _st_state(**overrides: object) -> dict:
    state: dict = {
        "raw_text": "换成腾讯",
        "quote_content": "单号：H-1",
        "quote_ticker_candidates": _CANDIDATES,
        "place_params": {
            "expected_action": "place",
            "orderList": [{"orderId": "H-1", "placeOrderWindCode": "旧标的"}],
        },
    }
    state.update(overrides)
    return state


class TestSwapSelectTickerNode:
    @pytest.mark.asyncio
    async def test_empty_candidate_list_skips_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """candidate_list 为空 → 不可能切标的，跳过 LLM 调用（Dify 原节点语义）。"""
        ainvoke = _patch_llm(
            monkeypatch, st_module, SwapSelectTickerOutput(picks=[])
        )
        out = await swap_select_ticker(
            _st_state(quote_ticker_candidates=[], place_params={
                "expected_action": "place",
                "orderList": [{"placeOrderWindCode": "旧标的"}],
            })
        )
        assert ainvoke.await_count == 0
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "旧标的"
        assert out["trace"][0].decision == "skipped:no_candidate_list"

    @pytest.mark.asyncio
    async def test_seq_pick_overwrites_windcode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", seq=2)]),
        )
        out = await swap_select_ticker(_st_state())
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "00700.HK"
        assert out["place_params"]["expected_action"] == "place"

    @pytest.mark.asyncio
    async def test_direct_ref_pick_overwrites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", directRef="贵州茅台")]),
        )
        out = await swap_select_ticker(_st_state())
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_empty_picks_keeps_original(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, st_module, SwapSelectTickerOutput(picks=[]))
        out = await swap_select_ticker(_st_state())
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "旧标的"

    @pytest.mark.asyncio
    async def test_unresolvable_pick_keeps_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", seq=99)]),
        )
        out = await swap_select_ticker(_st_state())
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "旧标的"

    @pytest.mark.asyncio
    async def test_trace_records_pick_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", seq=1)]),
        )
        out = await swap_select_ticker(_st_state())
        trace = out["trace"]
        assert trace[0].node == "swap_select_ticker"
        assert trace[0].decision == "picks=1"

    @pytest.mark.asyncio
    async def test_missing_place_params_defaults_to_empty_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, st_module, SwapSelectTickerOutput(picks=[]))
        out = await swap_select_ticker({"quote_ticker_candidates": _CANDIDATES})
        assert out["place_params"] == {"expected_action": "", "orderList": []}

    @pytest.mark.asyncio
    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(
            return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
        )
        monkeypatch.setattr(st_module, "get_qwen_complex", lambda: fake_base)
        out = await swap_select_ticker(_st_state())
        assert out["error"] is not None
        assert out["error"].node == "swap_select_ticker"
