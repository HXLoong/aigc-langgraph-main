"""一级路由节点测试(DSL v2 版)。

规则层细节测试在 tests/nodes/test_route_rules.py(移植源逐条对照);
本文件测节点行为(标签映射 / LLM 兜底触发条件 / swap_input_mode)与
golden 规则层精准率。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.nodes.intent_route as intent_route_module
from app.nodes.intent_route import intent_route
from app.nodes.route_rules import is_swap_transaction


# ============================================================
# 节点级(LLM 兜底 monkeypatch 替身)
# ============================================================


class TestIntentRouteNode:
    @pytest.mark.asyncio
    async def test_rule_hit_no_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """规则命中时绝不触发 LLM 兜底。"""

        async def boom(text, quote):  # pragma: no cover - 不应被调用
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

        async def boom(text, quote):  # pragma: no cover
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
        async def fake(text, quote):
            return "期权-文本"

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({"raw_text": "做 纳指 一笔"})
        assert result["product_type"] == "option"
        assert result["trace"][0].decision == "llm→期权-文本"

    @pytest.mark.asyncio
    async def test_llm_unknown_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(text, quote):
            return "unknown"

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({"raw_text": "你好，在吗"})
        assert result["product_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_empty_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(text, quote):
            return "unknown"

        monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake)
        result = await intent_route({})
        assert result["product_type"] == "unknown"


# ============================================================
# golden 规则层精准率(不调 LLM)
# ============================================================

_LABEL_TO_PT = {
    "互换-文本": "swap",
    "互换-图片": "swap",
    "互换-Excel": "swap",
    "期权-文本": "option",
    "期权平仓-文本": "option_close",
}


def _load_golden() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestGoldenRuleCoverage:
    def test_rule_layer_precision(self) -> None:
        """规则层触发时的精准率 ≥ 80%(触发但分错的比例 < 20%)。

        分母 = 规则层有输出(非 unknown)的 golden case;
        期望 = case 顶层 product_type 字段。
        """
        total = 0
        wrong: list[str] = []
        for case in _load_golden():
            expected = (case.get("category") or "").split("/")[0]
            if expected not in ("swap", "option", "option_close"):
                continue
            conv = case.get("conversation") or []
            if not conv:
                continue
            raw = conv[-1].get("raw_content", "") or ""
            quote = conv[-1].get("quote_desc") or conv[-1].get("quote_content")
            label = is_swap_transaction(raw, files=[], quote_content=quote)
            if label == "unknown":
                continue  # 规则层不触发,交 LLM,不计入精准率
            total += 1
            got = _LABEL_TO_PT.get(label)
            if got != expected:
                wrong.append(f"{case.get('id')}: {raw[:30]} → {label} (期望 {expected})")
        assert total > 0
        precision = 1 - len(wrong) / total
        assert precision >= 0.80, (
            f"规则层精准率 {precision:.1%} < 80%(触发但分错):\n" + "\n".join(wrong[:15])
        )
