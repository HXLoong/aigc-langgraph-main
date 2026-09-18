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
from app.subgraphs.swap.apply_picks import swap_apply_picks
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
            "orderList": [{"orderId": "H-1", "placeOrderShortname": "旧对手"}],
        },
    }
    state.update(overrides)
    return state


class TestSwapSelectCounterpartyNode:
    """ADR 0024 重构 3：节点只产出 LLM 指针（swap_counterparty_picks），不再直接改 place_params，
    以便与 select_ticker 并行；确定性查表覆盖由 swap_apply_picks 汇合节点完成。"""

    @pytest.mark.asyncio
    async def test_emits_picks_channel_not_place_params(
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
        assert "place_params" not in out
        assert out["swap_counterparty_picks"]["hasSignal"] is True
        assert out["swap_counterparty_picks"]["picks"][0]["letter"] == "B"

    @pytest.mark.asyncio
    async def test_no_signal_emits_empty_picks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, sc_module, SwapSelectCounterpartyOutput(hasSignal=False))
        out = await swap_select_counterparty(_sc_state(raw_text="暂时不换对手"))
        assert out["swap_counterparty_picks"] == {"hasSignal": False, "picks": []}

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
        assert trace[0].decision == "code,hasSignal=True,picks=1"
        assert trace[0].llm_output is not None

    @pytest.mark.asyncio
    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(
            return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
        )
        monkeypatch.setattr(sc_module, "get_qwen_complex", lambda: fake_base)
        out = await swap_select_counterparty(_sc_state(raw_text="帮我选一个适合的对手"))
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
            "orderList": [{"orderId": "H-1", "placeOrderWindCode": "旧标的"}],
        },
    }
    state.update(overrides)
    return state


class TestSwapSelectTickerNode:
    """同上：只产出 swap_ticker_picks 指针；candidate_list 为空时跳过 LLM 并产出空指针。"""

    @pytest.mark.asyncio
    async def test_empty_candidate_list_skips_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ainvoke = _patch_llm(
            monkeypatch, st_module, SwapSelectTickerOutput(picks=[])
        )
        out = await swap_select_ticker(_st_state(quote_ticker_candidates=[]))
        assert ainvoke.await_count == 0
        assert out["swap_ticker_picks"] == []
        assert "place_params" not in out
        assert out["trace"][0].decision == "skipped:no_candidate_list"

    @pytest.mark.asyncio
    async def test_emits_picks_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(
            monkeypatch,
            st_module,
            SwapSelectTickerOutput(picks=[SwapTickerPick(orderId="H-1", seq=2)]),
        )
        out = await swap_select_ticker(_st_state())
        assert "place_params" not in out
        assert out["swap_ticker_picks"][0]["seq"] == 2

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
        assert trace[0].decision == "llm,picks=1"

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


# ============================================================
# swap_apply_picks（汇合节点：确定性查表覆盖草稿）
# ============================================================


def _ap_state(**overrides: object) -> dict:
    state: dict = {
        "swap_counterparties": _TRS,
        "quote_ticker_candidates": _CANDIDATES,
        "place_params": {
            "orderList": [{"orderId": "H-1", "placeOrderShortname": "旧对手",
                           "placeOrderWindCode": "旧标的"}],
        },
        "swap_counterparty_picks": {"hasSignal": False, "picks": []},
        "swap_ticker_picks": [],
    }
    state.update(overrides)
    return state


class TestSwapApplyPicks:
    @pytest.mark.asyncio
    async def test_applies_both_picks_without_touching_expected_action(self) -> None:
        """expected_action 是顶层字段（ADR 0024 D2），汇合节点只改 orderList，不碰它。"""
        out = await swap_apply_picks(_ap_state(
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "letter": "B"}]},
            swap_ticker_picks=[{"orderId": "H-1", "seq": 2}],
        ))
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "测试111"
        assert order["placeOrderWindCode"] == "00700.HK"
        assert "expected_action" not in out["place_params"]
        assert "expected_action" not in out

    @pytest.mark.asyncio
    async def test_direct_name_and_direct_ref(self) -> None:
        out = await swap_apply_picks(_ap_state(
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "directName": "临沂阿凡提"}]},
            swap_ticker_picks=[{"orderId": "H-1", "directRef": "贵州茅台"}],
        ))
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "临沂阿凡提"
        assert order["placeOrderWindCode"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_no_signal_and_empty_picks_keep_original(self) -> None:
        out = await swap_apply_picks(_ap_state())
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "旧对手"
        assert order["placeOrderWindCode"] == "旧标的"

    @pytest.mark.asyncio
    async def test_unresolvable_picks_keep_original(self) -> None:
        out = await swap_apply_picks(_ap_state(
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "letter": "Z"}]},
            swap_ticker_picks=[{"orderId": "H-1", "seq": 99}],
        ))
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "旧对手"
        assert order["placeOrderWindCode"] == "旧标的"

    @pytest.mark.asyncio
    async def test_missing_picks_and_place_params_default_empty(self) -> None:
        out = await swap_apply_picks({"raw_text": "x"})
        assert out["place_params"] == {"orderList": []}

    @pytest.mark.asyncio
    async def test_clears_pick_channels_after_apply(self) -> None:
        out = await swap_apply_picks(_ap_state())
        assert out["swap_counterparty_picks"] is None
        assert out["swap_ticker_picks"] is None
