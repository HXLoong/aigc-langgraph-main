"""一级路由 intent_route 节点测试（ADR 0015）。

覆盖：
- 第 1 层订单号正则（4 个 prefix）
- 第 2 层关键词优先级表（option_close > option > swap）
- LLM 兜底用 monkeypatch 替身（不联网）
- 验证 trace decision 字段格式
- 用现有 30 条 golden 验证规则层路由分类
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nodes import intent_route as intent_route_module
from app.nodes.intent_route import (
    _match_keywords,
    _match_order_no,
    intent_route,
)


# ============================================================
# 第 1 层：订单号正则
# ============================================================


class TestOrderNoMatching:
    def test_swap_order_no(self) -> None:
        assert _match_order_no("撤 H-20260304-0000001") == "swap"

    def test_option_order_no(self) -> None:
        assert _match_order_no("期权撤单 OPT-20260304-0001") == "option"

    def test_option_close_co_prefix(self) -> None:
        assert _match_order_no("平 CO-20260304-4FE9C941 全部") == "option_close"

    def test_option_close_optg_prefix(self) -> None:
        assert _match_order_no("查询 OPTG-WFJJ202509030002 的状态") == "option_close"

    def test_no_order_no(self) -> None:
        assert _match_order_no("做一笔互换") is None

    def test_g029_order_no_over_keyword(self) -> None:
        """g029 真实 case：'互换订单 CO-... 帮我平仓' 应按订单号判 option_close。"""
        text = "互换订单 CO-20260304-ABCD1234 帮我平仓"
        assert _match_order_no(text) == "option_close"


# ============================================================
# 第 2 层：关键词优先级表
# ============================================================


class TestKeywordMatching:
    def test_option_close_pingcang(self) -> None:
        assert _match_keywords("帮我平仓") == "option_close"

    def test_option_close_chiccang(self) -> None:
        assert _match_keywords("我有哪些期权持仓") == "option_close"

    def test_option_close_regex_ping_quanbu(self) -> None:
        assert _match_keywords("平 茅台 全部") == "option_close"

    def test_option_keyword(self) -> None:
        assert _match_keywords("期权询价 腾讯") == "option"

    def test_option_xunjia(self) -> None:
        assert _match_keywords("询价茅台") == "option"

    def test_option_xueqiu(self) -> None:
        assert _match_keywords("雪球询价 腾讯控股") == "option"

    def test_swap_huhuan(self) -> None:
        assert _match_keywords("做一笔互换") == "swap"

    def test_swap_trs(self) -> None:
        assert _match_keywords("做一笔招商银行的 TRS") == "swap"

    def test_no_keyword_match(self) -> None:
        assert _match_keywords("你好，在吗") is None

    def test_priority_close_over_option(self) -> None:
        """g020 '我有哪些期权持仓' 必须判 option_close 不是 option（持仓优先）。"""
        assert _match_keywords("我有哪些期权持仓") == "option_close"


# ============================================================
# 节点级（含第 3 层 LLM 兜底，monkeypatch 替身）
# ============================================================


class TestIntentRouteNode:
    @pytest.mark.asyncio
    async def test_node_layer_1_order_no(self) -> None:
        result = await intent_route({"raw_text": "撤 H-20260304-0000001"})
        assert result["product_type"] == "swap"
        assert result["trace"][0].decision == "rule:order_no→swap"

    @pytest.mark.asyncio
    async def test_node_layer_2_keyword(self) -> None:
        result = await intent_route({"raw_text": "做一笔互换"})
        assert result["product_type"] == "swap"
        assert result["trace"][0].decision == "rule:keyword→swap"

    @pytest.mark.asyncio
    async def test_node_layer_3_llm_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 兜底场景：raw_text 无订单号无关键词，走 LLM。"""

        async def fake_classify(text: str) -> str:
            return "option"

        monkeypatch.setattr(
            intent_route_module, "_classify_with_llm", fake_classify
        )
        result = await intent_route({"raw_text": "做 纳指 一笔"})
        assert result["product_type"] == "option"
        assert result["trace"][0].decision == "llm→option"

    @pytest.mark.asyncio
    async def test_node_layer_3_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_classify(text: str) -> str:
            return "unknown"

        monkeypatch.setattr(
            intent_route_module, "_classify_with_llm", fake_classify
        )
        result = await intent_route({"raw_text": "你好，在吗"})
        assert result["product_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_node_handles_empty_raw_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_classify(text: str) -> str:
            return "unknown"

        monkeypatch.setattr(
            intent_route_module, "_classify_with_llm", fake_classify
        )
        result = await intent_route({})
        assert result["product_type"] == "unknown"


# ============================================================
# 用 30 条 golden 验证规则层覆盖率（不调 LLM）
# ============================================================


def _load_golden_with_strong_signal() -> list[dict]:
    """加载有订单号或关键词的 golden case（即规则层应该命中的）。"""
    path = Path(__file__).parent / "fixtures" / "golden.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # 过滤 unknown product_type 的 case（它们应该走 LLM 兜底，规则层不命中）
    return [
        c
        for c in cases
        if c.get("expected", {}).get("product_type") != "unknown"
    ]


class TestGoldenRuleCoverage:
    """规则层（不调 LLM）应该能覆盖大部分 golden case。"""

    @pytest.fixture
    def strong_signal_cases(self) -> list[dict]:
        return _load_golden_with_strong_signal()

    def test_rule_layer_covers_majority(
        self, strong_signal_cases: list[dict]
    ) -> None:
        """规则层（订单号 + 关键词）应覆盖 ≥ 80% 强信号 case。"""
        hit = 0
        miss: list[str] = []
        for case in strong_signal_cases:
            text = case["raw_content"]
            expected_pt = case["expected"]["product_type"]
            actual = _match_order_no(text) or _match_keywords(text)
            if actual == expected_pt:
                hit += 1
            else:
                miss.append(f"{case['id']}={text!r} expected={expected_pt} got={actual}")

        coverage = hit / len(strong_signal_cases)
        assert coverage >= 0.8, (
            f"规则层覆盖率 {coverage:.1%} < 80%。漏掉的 case:\n"
            + "\n".join(miss[:10])
        )

    def test_g029_order_no_over_keyword(
        self, strong_signal_cases: list[dict]
    ) -> None:
        """ADR 0015 业务硬约定：g029 必须按订单号判 option_close。"""
        g029 = next(c for c in strong_signal_cases if c["id"] == "g029")
        text = g029["raw_content"]
        actual = _match_order_no(text) or _match_keywords(text)
        assert actual == "option_close"
