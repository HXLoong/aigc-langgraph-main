"""Langfuse 实验使用同源确定性评分，平台字段不混入业务输入。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.golden import GoldenCase, dataset_expected, dataset_input
from scripts.langfuse.langfuse_eval import (
    _LocalItem,
    case_passed,
    deterministic_scores,
    item_case,
    passes_quality_gate,
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


def test_business_score_uses_all_deterministic_results() -> None:
    """不能只取第一个成功分数，也不能把缺少评分当作通过。"""
    passed, failed = SimpleNamespace(value=1), SimpleNamespace(value=0)
    for suite in ("business", "intent"):
        assert case_passed(suite, [passed, passed])
        assert not case_passed(suite, [passed, failed])
        assert not case_passed(suite, [])


def test_experiment_scores_do_not_use_reply_presence() -> None:
    """有回复但没有确定性评分时必须记录执行失败。"""
    scores = deterministic_scores(output={"reply_text": "有回复"})
    assert len(scores) == 1 and scores[0].value == 0
    scores = deterministic_scores(output={"evaluations": [{"name": "det_business_pass", "value": 0,
                                                          "comment": "金额不符"}]})
    assert scores[0].value == 0 and scores[0].comment == "金额不符"


def test_archived_items_are_not_selected_and_stable_case_id_is_supported() -> None:
    """平台状态与稳定用例 ID 共同决定明确执行范围。"""
    active = SimpleNamespace(id="uuid-active", status="ACTIVE", metadata={"id": "case-test"})
    archived = SimpleNamespace(id="uuid-old", status="ARCHIVED", metadata={"id": "case-old"})
    assert select_dataset_items([active, archived], None) == [active]
    assert select_dataset_items([active, archived], ["case-test"]) == [active]
    assert select_dataset_items([active, archived], ["case-old"]) == []


def test_empty_experiment_never_passes_quality_gate() -> None:
    """零条执行不能被阈值零解释成验收成功。"""
    assert not passes_quality_gate({"total": 0, "pass_rate": 0}, 0)


async def test_case_id_metadata_does_not_create_a_second_missing_item(monkeypatch) -> None:
    """平台 UUID 与稳定 case ID 不同时，统计仍只有一个实际用例。"""
    from scripts.langfuse import langfuse_eval as module

    async def execute(**kwargs):
        """使用执行器契约的已完成结果，仅隔离汇总层的外部执行。"""
        return {"case_id": "business-case", "status": "PASS", "passed": True, "turns": []}

    monkeypatch.setattr(module, "get_client", lambda: None)
    monkeypatch.setattr(module, "run_langgraph_pipeline", execute)
    item = {"id": "platform-uuid", "metadata": {"case_id": "business-case"}, "input": {}, "expected_output": {}}
    report = await module._run_items([item], suite="business", concurrency=1, base_url="http://test", prepare_java=False, report=None)
    assert report["total"] == report["passed"] == 1


@pytest.mark.parametrize("dataset,expected", [("intent/option", "intent"), ("biz/option_open", "business")])
def test_dataset_namespace_selects_suite(dataset: str, expected: str) -> None:
    """平台命名空间与本地目录使用同一套套件语义。"""
    assert resolve_suite(None, None, dataset) == expected
