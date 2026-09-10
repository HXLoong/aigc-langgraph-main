"""format_candidate_list 单测（对齐 ticker_列表格式化.py，Dify DSL v2 迁移）。"""
from __future__ import annotations

from app.subgraphs.ticker.tools import format_candidate_list


def test_json_string_parsed_and_deduped() -> None:
    result = format_candidate_list('["a", "b", "a", "", null, "b"]')
    assert result == ["a", "b"]


def test_list_input_used_directly() -> None:
    result = format_candidate_list(["贵州茅台", None, "贵州茅台", "", "腾讯"])
    assert result == ["贵州茅台", "腾讯"]


def test_invalid_json_string_returns_empty() -> None:
    assert format_candidate_list("not a json string") == []


def test_json_string_not_array_returns_empty() -> None:
    assert format_candidate_list('{"a": 1}') == []


def test_non_list_non_str_returns_empty() -> None:
    assert format_candidate_list(123) == []  # type: ignore[arg-type]


def test_empty_list_returns_empty() -> None:
    assert format_candidate_list([]) == []


def test_order_preserved_first_occurrence() -> None:
    result = format_candidate_list(["b", "a", "b", "c", "a"])
    assert result == ["b", "a", "c"]
