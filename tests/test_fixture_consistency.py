"""基准迁移检查必须检测数据丢失、空文件和重复编号。"""
from copy import deepcopy

from scripts import check_fixture_consistency as checker
from scripts import merge_golden


def test_current_golden_namespace_is_accepted() -> None:
    assert checker.check_id_naming("golden", [
        {"id": "swap-001"}, {"id": "opt-001"}, {"id": "opt_close-001"}, {"id": "query-001"},
    ]) == []
    assert checker.check_id_naming("golden", [{"id": "invalid-001"}])


def test_empty_and_duplicate_fixtures_are_rejected() -> None:
    assert checker.check_id_naming("golden", [])
    assert checker.check_id_naming("golden", [{"id": "opt-001"}, {"id": "opt-001"}])


def test_missing_anchor_and_missing_current_case_are_rejected() -> None:
    anchors = [{"id": f"g{i:03d}"} for i in range(1, 31)]
    assert checker.check_anchors_present(anchors) == []
    assert checker.check_anchors_present(anchors[:-1])
    case = {"conversation": [{"raw_content": "期限补充为 1M"}]}
    assert checker.check_unified_is_superset([case], [])
    assert checker.check_unified_is_superset([case], [case]) == []


def test_merge_preserves_history_and_current_multiturn_expected_values() -> None:
    old = {"id": "opt-001", "conversation": [{"raw_content": "询价"}], "expected": {"output": "旧"}}
    current = {
        "id": "opt-001", "category": "option/inquiry",
        "conversation": [{"raw_content": "询价"}, {"raw_content": "补充期限"}],
        "expected": {"output": "新", "product_type": "option"},
    }
    before = deepcopy(current)
    converted = merge_golden.convert_golden(current)
    assert converted == before
    merged = merge_golden.merge_archive([old], [("golden.jsonl", [converted])])
    assert merged[0] == old
    assert merged[1]["id"] == "opt-002"
    assert merged[1]["source_case_id"] == "opt-001"
    assert merged[1]["source_fixture"] == "golden.jsonl"
    assert merged[1]["conversation"] == current["conversation"]
    assert merged[1]["expected"] == current["expected"]
    assert current == before
    assert merge_golden.merge_archive(merged, [("golden.jsonl", [current])]) == merged
