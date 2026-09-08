"""LangFuse Judge regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from scripts.langfuse_eval import judge_by_deepseek


def test_judge_does_not_return_json_parse_failure_after_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A textless first response must not become a JSON parsing failure."""

    class FakeMessages:
        def __init__(self) -> None:
            self.call_count = 0

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            self.call_count += 1
            if self.call_count == 1:
                return SimpleNamespace(
                    content=[SimpleNamespace(type="thinking", thinking="still reasoning")],
                    stop_reason="max_tokens",
                )
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"pass":true,"score":1.0,"reason":"expected result"}',
                    )
                ],
                stop_reason="end_turn",
            )

    class FakeAnthropic:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)

    evaluation = judge_by_deepseek(
        output={"reply_text": "order placed"},
        expected_output="order placed successfully",
        metadata={"overview": "swap order placement"},
    )

    assert evaluation.value == 1.0
    assert evaluation.comment == "expected result"
    assert not evaluation.comment.startswith("JSON")
