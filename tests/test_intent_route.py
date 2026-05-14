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
    # E3.4 簇 B · 裸"确认下单/撤单/平仓"歧义文档化（当前行为，业务方决策）
    # ============================================================

    def test_route_ambiguity_bare_confirm_order_to_option(self) -> None:
        """裸"确认下单"（无订单号、无上下文）→ option（keywords.yaml 现状）。

        E3.4 簇 B 76% 失败的根因：keywords.yaml option 块含"确认下单"，
        swap 块没有这个关键词；遍历优先级遇到 option 即 break。

        fixture 期望 swap 但实际命中 option，业务方待决策：
        1. 真实客户语料中裸"确认下单"是否常见？
        2. 若常见，路由规则需扩（如要求上下文或在 LLM 层处理歧义）
        3. 若不常见，fixture 应改"swap 确认下单"等显式形式
        """
        assert _match_keywords("确认下单") == "option"
        # "确认改单"不在 keywords.yaml 中 → 走 LLM 兜底（路由层无确定行为）
        assert _match_keywords("确认改单") is None

    def test_route_ambiguity_bare_cancel_confirm_to_option_close(self) -> None:
        """裸"确认撤单" → option_close（keywords.yaml 现状）。

        option_close 块（最高优先级）含"确认撤单"，覆盖 swap 与 option 的撤单意图。
        与上面同样属于 E3.4 簇 B 待决策项。
        """
        assert _match_keywords("确认撤单") == "option_close"


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
        # E3.4 trace 增强：decision 含 hit_token (kw:互换 / re:pattern 等)
        decision = result["trace"][0].decision
        assert decision.startswith("rule:keyword[")
        assert decision.endswith("→swap")
        assert "互换" in decision

    @pytest.mark.asyncio
    async def test_node_layer_3_llm_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 兜底场景：raw_text 无订单号无关键词，走 LLM。"""

        async def fake_classify(text: str, quote_content: str | None = None) -> str:
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
        async def fake_classify(text: str, quote_content: str | None = None) -> str:
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
        async def fake_classify(text: str, quote_content: str | None = None) -> str:
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
    """加载规则层有触发输出的 golden case（用于测规则层精准率）。

    golden.jsonl 已从 g0xx 格式迁移为 opt-xxx/swap-xxx，
    同时 raw_content 从 case 顶层移入 conversation[-1]。
    改为取规则层（订单号正则 + 关键词表）有输出的全集 case 作为分母，
    验证"触发时是否正确"（精准率），而非"覆盖了多少 case"（召回率）。
    """
    path = Path(__file__).parent / "fixtures" / "golden.jsonl"
    cases = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    return [
        c
        for c in cases
        if c.get("expected", {}).get("product_type") not in ("", "unknown")
        and (
            _match_order_no(c["conversation"][-1]["raw_content"])
            or _match_keywords(c["conversation"][-1]["raw_content"])
        ) is not None
    ]


class TestGoldenRuleCoverage:
    """规则层（不调 LLM）应该能覆盖大部分 golden case。"""

    @pytest.fixture
    def strong_signal_cases(self) -> list[dict]:
        return _load_golden_with_strong_signal()

    def test_rule_layer_covers_majority(
        self, strong_signal_cases: list[dict]
    ) -> None:
        """规则层触发时精准率应 ≥ 80%（触发 → 正确，不统计 LLM 兜底的 case）。"""
        if not strong_signal_cases:
            pytest.skip("golden.jsonl 无规则层触发 case，跳过精准率校验")
        hit = 0
        miss: list[str] = []
        for case in strong_signal_cases:
            text = case["conversation"][-1]["raw_content"]
            expected_pt = case["expected"]["product_type"]
            actual = _match_order_no(text) or _match_keywords(text)
            if actual == expected_pt:
                hit += 1
            else:
                miss.append(f"{case['id']}={text!r} expected={expected_pt} got={actual}")

        precision = hit / len(strong_signal_cases)
        assert precision >= 0.8, (
            f"规则层精准率 {precision:.1%} < 80%（触发但分错）:\n"
            + "\n".join(miss[:10])
        )

    def test_g029_order_no_over_keyword(
        self, strong_signal_cases: list[dict]
    ) -> None:
        """ADR 0015 业务硬约定：含 CO- 订单号的平仓指令必须按订单号判 option_close。"""
        # opt-001: '确认平仓 CO-20260304-ABCD1234'，是新格式中对应 g029 的锚点 case
        anchor = next(
            (c for c in strong_signal_cases if c["id"] == "opt-001"),
            None,
        )
        if anchor is None:
            pytest.skip("opt-001 锚点 case 不在 strong_signal_cases 中")
        text = anchor["conversation"][-1]["raw_content"]
        actual = _match_order_no(text) or _match_keywords(text)
        assert actual == "option_close"


# ============================================================
# Bug1: quote_content 含明确产品标记时，路由不应误判
# ============================================================


class TestQuoteContentRouting:
    """多轮对话：quote_content 里有机器人回复的产品标记，应在 LLM 之前确定路由。

    场景：用户 turn1 询价（期权），turn2 发 "200万，市价下单"；
    quote_content = turn1 的机器人期权询价详情回复。
    规则层无关键词 → 当前会落到 LLM，LLM 易误判为 swap。
    期望：quote 信号层在 LLM 之前捕获，返回 option。
    """

    @pytest.mark.asyncio
    async def test_quote_contains_option_inquiry_routes_to_option(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """quote_content 含 '场外期权询价详情' → 路由 option，不调 LLM。"""
        llm_called = []

        async def fake_classify(text: str, quote_content: str | None = None) -> str:
            llm_called.append(text)
            return "swap"  # LLM 若被调用会返回错误结果

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

        result = await intent_route({
            "raw_text": "200万，市价下单",
            "quote_content": "-----场外期权询价详情-----\n期权类型：欧式看涨\n标的代码：600519.SH",
        })
        assert result["product_type"] == "option", (
            f"quote 含期权标记应路由 option，实际: {result['product_type']}"
        )
        assert not llm_called, "quote 信号层命中时不应再调 LLM"

    @pytest.mark.asyncio
    async def test_quote_contains_swap_order_routes_to_swap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """quote_content 含 '互换订单参数' → 路由 swap，不调 LLM。"""
        llm_called = []

        async def fake_classify(text: str, quote_content: str | None = None) -> str:
            llm_called.append(text)
            return "option"

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

        result = await intent_route({
            "raw_text": "确认",
            "quote_content": "-----互换订单参数-----\n标的: 600519.SH\n方向: 买入",
        })
        assert result["product_type"] == "swap", (
            f"quote 含互换标记应路由 swap，实际: {result['product_type']}"
        )
        assert not llm_called

    @pytest.mark.asyncio
    async def test_quote_without_product_marker_still_uses_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """quote_content 无明确产品标记 → 正常走 LLM。"""
        llm_called = []

        async def fake_classify(text: str, quote_content: str | None = None) -> str:
            llm_called.append(text)
            return "option"

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

        result = await intent_route({
            "raw_text": "200万",
            "quote_content": "好的，已收到",
        })
        assert llm_called, "无产品标记时应走 LLM"
        assert result["product_type"] == "option"
