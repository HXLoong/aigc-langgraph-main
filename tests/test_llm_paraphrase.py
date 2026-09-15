"""LLM paraphrase tests for the active fixture dialect."""
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
from harness.golden import GoldenCase, TurnSpec


def _patch_llm(monkeypatch: pytest.MonkeyPatch, batch: ParaphraseBatch) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=batch)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(lp_module, "get_qwen_thinking", lambda: fake_base)


def _seed(text: str = "做一笔互换") -> GoldenCase:
    return GoldenCase(
        id="g001",
        category="swap/place_order",
        turns=[TurnSpec(send_text=text, at_bot=True)],
        expected={"product_type": "swap", "intent": "place_order_request"},
    )


def test_paraphrased_case_uses_send_text() -> None:
    case = ParaphrasedCase(send_text="互换下单", notes="缩写")
    assert case.send_text == "互换下单"
    assert case.quote_previous is None


@pytest.mark.asyncio
async def test_paraphrase_returns_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = ParaphraseBatch(
        variants=[
            ParaphrasedCase(send_text="招行互换 1000 手", notes="缩写"),
            ParaphrasedCase(send_text="帮我做一笔 TRS", notes="口语化"),
        ]
    )
    _patch_llm(monkeypatch, batch)
    variants = await paraphrase_case(_seed(), num_variants=2)
    assert [item.send_text for item in variants] == ["招行互换 1000 手", "帮我做一笔 TRS"]


def test_to_golden_dict_emits_active_schema() -> None:
    out = to_golden_dict(_seed(), ParaphrasedCase(send_text="变体表达", notes="缩写"), "g001-v1")
    assert out["id"] == "g001-v1"
    assert out["send_text"] == "变体表达"
    assert out["expected"] == _seed().expected
    assert out["sub_scenes"] == []
    assert "raw_content" not in out


def test_render_review_markdown_uses_send_text() -> None:
    md = render_review_markdown(
        [(_seed(), [ParaphrasedCase(send_text="招行互换", notes="缩写")])]
    )
    assert "## 种子 g001" in md
    assert "做一笔互换" in md
    assert "招行互换" in md
    assert "[ ]" in md
