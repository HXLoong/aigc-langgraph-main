"""LLM 对抗式 paraphrase 测试（mock LLM，不联网）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.case_generator import llm_paraphrase as lp_module
from harness.case_generator.llm_paraphrase import (
    ParaphraseBatch,
    ParaphrasedCase,
    paraphrase_case,
    render_review_markdown,
    to_golden_dict,
)
from harness.golden import GoldenCase


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, batch: ParaphraseBatch
) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=batch)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(lp_module, "get_qwen_thinking", lambda: fake_base)


# ============================================================
# Pydantic schema
# ============================================================


class TestParaphrasedCase:
    def test_minimal(self) -> None:
        case = ParaphrasedCase(raw_content="互换下单", notes="缩写")
        assert case.raw_content == "互换下单"
        assert case.quote_content is None

    def test_with_quote(self) -> None:
        case = ParaphrasedCase(
            raw_content="确认", quote_content="订单 H-1", notes="参数补充"
        )
        assert case.quote_content == "订单 H-1"


# ============================================================
# paraphrase_case 调用
# ============================================================


@pytest.mark.asyncio
class TestParaphraseCase:
    async def test_paraphrase_returns_variants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch = ParaphraseBatch(
            variants=[
                ParaphrasedCase(raw_content="招行 互换 1000 手", notes="缩写"),
                ParaphrasedCase(
                    raw_content="帮我做一笔TRS", notes="口语化"
                ),
            ]
        )
        _patch_llm(monkeypatch, batch)
        seed = GoldenCase(
            id="g001",
            category="swap/place_order",
            raw_content="做一笔招商银行的 TRS",
            expected={"product_type": "swap", "intent": "place_order_request"},
        )
        variants = await paraphrase_case(seed, num_variants=2)
        assert len(variants) == 2
        assert variants[0].notes == "缩写"

    async def test_empty_variants_when_llm_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, ParaphraseBatch(variants=[]))
        seed = GoldenCase(
            id="g001",
            category="swap/place_order",
            raw_content="x",
            expected={},
        )
        assert await paraphrase_case(seed) == []


# ============================================================
# to_golden_dict
# ============================================================


def test_to_golden_dict_preserves_expected() -> None:
    seed = GoldenCase(
        id="g001",
        category="swap/place_order",
        raw_content="原话",
        expected={"product_type": "swap", "intent": "place_order_request"},
    )
    paraphrased = ParaphrasedCase(
        raw_content="变体表达", quote_content=None, notes="缩写"
    )
    out = to_golden_dict(seed, paraphrased, new_id="g001-v1")

    assert out["id"] == "g001-v1"
    assert out["category"] == "swap/place_order"
    assert out["raw_content"] == "变体表达"
    assert out["expected"] == seed.expected  # expected 不变
    assert out["source"] == "llm_paraphrase"
    assert "g001" in out["notes"]  # 含 seed 引用


def test_to_golden_dict_with_quote() -> None:
    seed = GoldenCase(
        id="g019",
        category="option/confirm_from_quote",
        raw_content="确认第二笔",
        quote_content="原引用",
        expected={"product_type": "option", "intent": "confirm_order"},
    )
    paraphrased = ParaphrasedCase(
        raw_content="确认第2笔", quote_content="新引用", notes="数字变体"
    )
    out = to_golden_dict(seed, paraphrased, "g019-v1")
    assert out["quote_content"] == "新引用"


# ============================================================
# render_review_markdown
# ============================================================


class TestRenderReviewMarkdown:
    def test_includes_seeds_and_variants(self) -> None:
        seed = GoldenCase(
            id="g001",
            category="swap/place_order",
            raw_content="做一笔TRS",
            expected={"product_type": "swap", "intent": "place_order_request"},
        )
        variants = [
            ParaphrasedCase(raw_content="招行互换", notes="缩写"),
            ParaphrasedCase(
                raw_content="帮我做TRS", quote_content=None, notes="口语化"
            ),
        ]
        md = render_review_markdown([(seed, variants)])

        assert "## 种子 g001" in md
        assert "做一笔TRS" in md
        assert "招行互换" in md
        assert "帮我做TRS" in md
        # checkboxes 待业务方打勾
        assert "[ ]" in md
        assert "g001-v1" in md
        assert "g001-v2" in md

    def test_renders_variant_with_quote_content(self) -> None:
        seed = GoldenCase(
            id="g019",
            category="option/confirm_from_quote",
            raw_content="确认第二笔",
            expected={"intent": "confirm_order"},
        )
        variants = [
            ParaphrasedCase(
                raw_content="确认2",
                quote_content="原引用消息",
                notes="数字变体",
            ),
        ]
        md = render_review_markdown([(seed, variants)])
        assert "原引用消息" in md
        assert "quote:" in md

    def test_empty_input(self) -> None:
        md = render_review_markdown([])
        # 仍含 header
        assert "LLM 对抗式变体候选清单" in md
        # 没 seed 段
        assert "## 种子" not in md
