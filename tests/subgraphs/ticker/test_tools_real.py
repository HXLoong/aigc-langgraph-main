"""ticker 4 工具真实现单测（#17 #18 #19）。

mock 策略：
- tokenize：纯规则，不 mock
- completeness / rank：mock TickerClientHttpx HTTP 响应
- infer_code：mock get_inference_prompt + LLM
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.tools import (
    RANK_AUTO_PICK_GAP,
    clear_infer_prompt_cache,
    completeness,
    infer_code,
    rank,
    tokenize,
)
from app.tools.ticker_client import SecuritiesInstrumentRespVO


# ============================================================
# tokenize · 纯规则
# ============================================================


class TestTokenize:
    def test_empty_returns_empty(self) -> None:
        assert tokenize.invoke({"raw_text": ""}) == []
        assert tokenize.invoke({"raw_text": "   "}) == []

    def test_basic_space_split(self) -> None:
        assert tokenize.invoke({"raw_text": "买 腾讯 1000 股"}) == [
            "买", "腾讯", "1000", "股",
        ]

    def test_full_code_with_suffix_emits_both(self) -> None:
        """`0700.HK` 应同时输出完整代码和无后缀片段。"""
        assert tokenize.invoke({"raw_text": "0700.HK"}) == [
            "0700.HK", "0700",
        ]

    def test_full_code_with_a_share_suffix(self) -> None:
        assert tokenize.invoke({"raw_text": "600519.SH"}) == [
            "600519.SH", "600519",
        ]

    def test_multiple_separators(self) -> None:
        """支持中英文逗号 / 分号 / 顿号 / 斜杠 / 竖线 / @。"""
        assert tokenize.invoke({"raw_text": "600519/000858"}) == [
            "600519", "000858",
        ]
        assert tokenize.invoke({"raw_text": "腾讯，阿里；美团、京东"}) == [
            "腾讯", "阿里", "美团", "京东",
        ]
        assert tokenize.invoke({"raw_text": "TRS|huhuan|互换"}) == [
            "TRS", "huhuan", "互换",
        ]

    def test_embedded_4_to_6_digits_extracted(self) -> None:
        """嵌入的 4-6 位数字应单独提取为 code keyword。"""
        assert tokenize.invoke({"raw_text": "02513智谱"}) == [
            "02513", "智谱",
        ]
        assert tokenize.invoke({"raw_text": "贵州茅台600519"}) == [
            "600519", "贵州茅台",
        ]

    def test_short_digits_not_treated_as_code(self) -> None:
        """1-3 位数字不算代码 keyword（按 tokenize.md 规则）。

        无 4-6 位嵌入数字 → token 不拆分，整体保留。
        """
        result = tokenize.invoke({"raw_text": "2月WTI原油"})
        assert "2" not in result
        # 因为没有 4-6 位数字，token 整体保留
        assert "2月WTI原油" in result

    def test_dedupe_preserves_order(self) -> None:
        """重复 token 仅保留首次出现位置。"""
        assert tokenize.invoke({"raw_text": "腾讯 腾讯 阿里"}) == ["腾讯", "阿里"]

    def test_real_world_complex(self) -> None:
        """复杂混合输入。"""
        result = tokenize.invoke(
            {"raw_text": "买入 0700.HK 腾讯 1000 股 限价 350"}
        )
        assert "0700.HK" in result
        assert "0700" in result
        assert "腾讯" in result
        assert "1000" in result
        assert "350" in result


# ============================================================
# completeness · mock securities-instrument/select
# ============================================================


def _mock_client(monkeypatch: pytest.MonkeyPatch, results: list) -> MagicMock:
    """工厂：让 _make_client 返回的 client.search_securities_instrument 返回指定 results。"""
    client = MagicMock()
    client.search_securities_instrument = AsyncMock(return_value=results)
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    return client


def _resp(wind: str, score: int = 0) -> SecuritiesInstrumentRespVO:
    return SecuritiesInstrumentRespVO(
        windCode=wind, insShtDesc=wind, relevanceScore=score
    )


class TestCompleteness:
    def test_complete_when_single_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, [_resp("00700.HK")])
        result = completeness.invoke({"keyword": "00700.HK"})
        assert result["is_complete"] is True
        assert result["candidates"] == 1

    def test_not_complete_when_no_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, [])
        result = completeness.invoke({"keyword": "腾讯"})
        assert result["is_complete"] is False
        assert result["candidates"] == 0

    def test_not_complete_when_multi_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """isFull=true 模式下命中 ≥ 2 视为不完整（歧义）。"""
        _mock_client(
            monkeypatch,
            [_resp("00700.HK"), _resp("700.HK")],
        )
        result = completeness.invoke({"keyword": "700"})
        assert result["is_complete"] is False
        assert result["candidates"] == 2

    def test_backend_error_falls_back_to_suffix_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """后端不可达 → 退化后缀规则，不死锁。"""
        client = MagicMock()
        client.search_securities_instrument = AsyncMock(
            side_effect=ConnectionError("backend down")
        )
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

        # 含已知后缀
        result = completeness.invoke({"keyword": "00700.HK"})
        assert result["is_complete"] is True
        assert result.get("fallback") is True

        # 不含后缀
        result = completeness.invoke({"keyword": "腾讯"})
        assert result["is_complete"] is False

    def test_empty_keyword(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = completeness.invoke({"keyword": ""})
        assert result["is_complete"] is False


# ============================================================
# rank · mock + 分差 / HITL 触发
# ============================================================


class TestRank:
    def test_no_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(monkeypatch, [])
        result = rank.invoke({"keyword": "不存在"})
        assert result["winner"] is None
        assert result["needs_hitl"] is False
        assert result["reason"] == "no_match"

    def test_single_match_auto_pick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, [_resp("00700.HK", 0)])
        result = rank.invoke({"keyword": "腾讯"})
        assert result["winner"] == "00700.HK"
        assert result["needs_hitl"] is False
        assert result["reason"] == "single_match"

    def test_multi_match_with_large_gap_auto_picks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """top1.score=0 + top2.score=10 → gap=10 ≥ 阈值 → 自动选 top1。"""
        _mock_client(
            monkeypatch,
            [_resp("00700.HK", 0), _resp("OTHER.HK", 10)],
        )
        result = rank.invoke({"keyword": "腾讯"})
        assert result["winner"] == "00700.HK"
        assert result["needs_hitl"] is False
        assert "auto_pick_gap" in result["reason"]

    def test_multi_match_with_small_gap_triggers_hitl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """top1.score=5 + top2.score=10 → gap=5 < 10 → HITL。"""
        _mock_client(
            monkeypatch,
            [_resp("00700.HK", 5), _resp("OTHER.HK", 10)],
        )
        result = rank.invoke({"keyword": "腾讯"})
        assert result["winner"] is None
        assert result["needs_hitl"] is True
        assert "hitl_gap" in result["reason"]
        assert len(result["candidates"]) == 2

    def test_backend_error_returns_safe_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock()
        client.search_securities_instrument = AsyncMock(
            side_effect=TimeoutError("upstream timeout")
        )
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
        result = rank.invoke({"keyword": "腾讯"})
        assert result["winner"] is None
        assert result["needs_hitl"] is False
        assert "backend_error" in result["reason"]

    def test_auto_pick_gap_constant(self) -> None:
        assert RANK_AUTO_PICK_GAP == 10


# ============================================================
# infer_code · mock 动态 prompt + LLM
# ============================================================


class TestInferCode:
    def setup_method(self) -> None:
        clear_infer_prompt_cache()

    def teardown_method(self) -> None:
        clear_infer_prompt_cache()

    def test_invokes_llm_with_dynamic_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """正常路径：拉动态 prompt + LLM 推断。"""
        client = MagicMock()
        client.get_inference_prompt = AsyncMock(
            return_value="动态约束：港股优先用 5 位代码"
        )
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

        # mock LLM
        with patch.object(tools_mod, "_llm_infer", return_value="00700.HK"):
            result = infer_code.invoke({"keyword": "腾讯"})
            assert result == "00700.HK"

    def test_backend_unavailable_degrades_to_static_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """后端拉 prompt 失败 → 不阻塞，仅静态 prompt + LLM。"""
        client = MagicMock()
        client.get_inference_prompt = AsyncMock(
            side_effect=ConnectionError("backend down")
        )
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

        with patch.object(tools_mod, "_llm_infer", return_value="00700.HK"):
            result = infer_code.invoke({"keyword": "腾讯"})
            assert result == "00700.HK"

    def test_llm_failure_returns_keyword(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 调用失败 → 原样返回 keyword（保守）。"""
        client = MagicMock()
        client.get_inference_prompt = AsyncMock(return_value="")
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

        with patch.object(
            tools_mod, "_llm_infer", side_effect=RuntimeError("LLM dead")
        ):
            result = infer_code.invoke({"keyword": "腾讯"})
            assert result == "腾讯"

    def test_empty_keyword_short_circuits(self) -> None:
        assert infer_code.invoke({"keyword": ""}) == ""
        assert infer_code.invoke({"keyword": "  "}) == ""

    def test_dynamic_prompt_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5min LRU：相同进程内连续调用，get_inference_prompt 只跑一次。"""
        client = MagicMock()
        client.get_inference_prompt = AsyncMock(return_value="片段")
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

        with patch.object(tools_mod, "_llm_infer", return_value="X"):
            infer_code.invoke({"keyword": "a"})
            infer_code.invoke({"keyword": "b"})
            infer_code.invoke({"keyword": "c"})

        assert client.get_inference_prompt.await_count == 1

    def test_dynamic_prompt_sanitized(self) -> None:
        from app.subgraphs.ticker.tools import _sanitize_dynamic_prompt

        # trim
        assert _sanitize_dynamic_prompt("  hello  ") == "hello"
        # 控制字符过滤
        assert _sanitize_dynamic_prompt("a\x00b\x07c") == "abc"
        # 长度上限
        long = "x" * 5000
        assert len(_sanitize_dynamic_prompt(long)) == 4096
