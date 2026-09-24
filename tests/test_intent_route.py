"""一级路由节点测试(DSL v2 版)。

规则层细节测试在 tests/nodes/test_route_rules.py(移植源逐条对照);
本文件测节点行为(标签映射 / LLM 兜底触发条件 / swap_input_mode)。
"""
from __future__ import annotations

import pytest

import app.nodes.intent_route as intent_route_module
from app.nodes.intent_route import intent_route
from tests.intent_fixtures import route_reply

# ============================================================
# 节点级(LLM 兜底 monkeypatch 替身)
# ============================================================


class TestIntentRouteNode:
    @pytest.mark.asyncio
    async def test_rule_hit_no_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """规则命中时绝不触发 LLM 兜底。"""

        async def boom(text, quote, history=None):  # pragma: no cover - 不应被调用
            raise AssertionError("规则命中不应调 LLM")

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", boom)
        result = await intent_route({"raw_text": "撤掉 H-20260101-0000000001"})
        assert result["product_type"] == "swap"
        assert result["swap_input_mode"] == "text"
        assert result["trace"][0].decision == "rule→互换-文本"

    @pytest.mark.asyncio
    async def test_option_open_order_no_routes_option(self) -> None:
        """DSL v2:Q- 单号 = 期权开仓/报价单号 → option(旧版误归 option_close)。"""
        result = await intent_route({"raw_text": "Q-20260101-0000000001 确认"})
        assert result["product_type"] == "option"

    @pytest.mark.asyncio
    async def test_close_contract_routes_option_close(self) -> None:
        result = await intent_route({"raw_text": "OPTG-SZZSCF20250030 全部平掉"})
        assert result["product_type"] == "option_close"

    @pytest.mark.asyncio
    async def test_image_files_route_swap_image(self) -> None:
        result = await intent_route(
            {"raw_text": "", "input_files": [{"type": "image"}]}
        )
        assert result["product_type"] == "swap"
        assert result["swap_input_mode"] == "image"

    @pytest.mark.asyncio
    async def test_excel_files_route_swap_excel(self) -> None:
        result = await intent_route(
            {"raw_text": "", "input_files": [{"type": "document", "extension": ".xlsx"}]}
        )
        assert result["product_type"] == "swap"
        assert result["swap_input_mode"] == "excel"

    @pytest.mark.asyncio
    async def test_unrecognized_files_skip_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """混合文件 → 无法识别文件类型 → 直接 unknown,不走 LLM(DSL 同语义)。"""

        async def boom(text, quote, history=None):  # pragma: no cover
            raise AssertionError("文件无法识别不应调 LLM")

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", boom)
        result = await intent_route(
            {
                "raw_text": "",
                "input_files": [{"type": "image"}, {"type": "document", "extension": ".pdf"}],
            }
        )
        assert result["product_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_llm_fallback_label_mapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(text, quote, history=None):
            return route_reply('期权-文本', text)

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({"raw_text": "做 纳指 一笔"})
        assert result["product_type"] == "option"
        assert result["trace"][0].decision == "llm→期权-文本"

    @pytest.mark.asyncio
    async def test_llm_unknown_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(text, quote, history=None):
            return route_reply('unknown', text)

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({"raw_text": "你好，在吗"})
        assert result["product_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_empty_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(text, quote, history=None):
            return route_reply('unknown', text)

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({})
        assert result["product_type"] == "unknown"


# ============================================================
# golden 规则层精准率(不调 LLM)
# ============================================================

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

        async def fake_classify(text: str, quote_content: str | None = None, history_messages: object = None) -> str:
            llm_called.append(text)
            return route_reply('互换-文本', text)  # LLM 若被调用会返回错误结果

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
        """quote_content 含后端互换下单卡 → 路由 swap，不调 LLM。"""
        llm_called = []

        async def fake_classify(text: str, quote_content: str | None = None, history_messages: object = None) -> str:
            llm_called.append(text)
            return route_reply('期权-文本', text)

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

        result = await intent_route({
            "raw_text": "确认",
            "quote_content": "-----互换下单确认-----\n标的: 600519.SH\n方向: 买入",
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

        async def fake_classify(text: str, quote_content: str | None = None, history_messages: object = None) -> str:
            llm_called.append(text)
            return route_reply('期权-文本', text)

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

        result = await intent_route({
            "raw_text": "200万",
            "quote_content": "好的，已收到",
        })
        assert llm_called, "无产品标记时应走 LLM"
        assert result["product_type"] == "option"
