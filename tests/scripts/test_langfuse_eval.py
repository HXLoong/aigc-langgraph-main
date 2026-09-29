"""Langfuse 实验只执行并上传输出，平台字段不混入业务输入。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.golden import GoldenCase, dataset_expected, dataset_input
from scripts.langfuse.langfuse_eval import (
    _LocalItem,
    item_case,
    resolve_suite,
    select_dataset_items,
)


def _case() -> GoldenCase:
    """使用已有格式的两轮输入，逐轮提供明确期望。"""
    return GoldenCase(id="case-test", category="option", turns=[
        {"send_text": "询价", "expected": {"intent": "new_inquiry"}},
        {"send_text": "确认下单", "quote_previous": True, "expected": {"intent": "confirm_order"}},
    ])


def test_dataset_roundtrip_preserves_input_and_each_turn_expectation() -> None:
    """同一 fixture 在本地和 Dataset 入口具有相同输入及断言。"""
    case = _case()
    item = _LocalItem(case).as_item()
    assert item["input"] == dataset_input(case) and "expected" not in item["input"]
    assert item["expected_output"] == dataset_expected(case)
    reconstructed = item_case(item)
    assert reconstructed.id == case.id
    assert [turn.expected for turn in reconstructed.turns] == [turn.expected for turn in case.turns]
    assert [turn.send_text for turn in reconstructed.turns] == ["询价", "确认下单"]


def test_archived_items_are_not_selected_and_stable_case_id_is_supported() -> None:
    """平台状态与稳定用例 ID 共同决定明确执行范围。"""
    active = SimpleNamespace(id="uuid-active", status="ACTIVE", metadata={"id": "case-test"})
    archived = SimpleNamespace(id="uuid-old", status="ARCHIVED", metadata={"id": "case-old"})
    assert select_dataset_items([active, archived], None) == [active]
    assert select_dataset_items([active, archived], ["case-test"]) == [active]
    assert select_dataset_items([active, archived], ["case-old"]) == []


async def test_experiment_does_not_register_python_evaluators(monkeypatch) -> None:
    """Python 只提交输出，Score 由 Langfuse 中已配置的 JS Rule 生成。"""
    from scripts.langfuse import langfuse_eval as module

    captured = {}

    class Client:
        def run_experiment(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(name="test-run")

    monkeypatch.setattr(module, "get_client", Client)
    monkeypatch.setattr(module, "flush", lambda: None)
    item = {"id": "platform-uuid", "metadata": {"case_id": "business-case"}, "input": {}, "expected_output": {}}
    await module._run_items([item], suite="business", concurrency=1, base_url="http://test", prepare_java=False)
    assert "evaluators" not in captured
    assert captured["data"] == [item]


@pytest.mark.parametrize("dataset,expected", [("intent/option", "intent"), ("biz/option_open", "business")])
def test_dataset_namespace_selects_suite(dataset: str, expected: str) -> None:
    """平台命名空间与本地目录使用同一套套件语义。"""
    assert resolve_suite(None, None, dataset) == expected
