"""merge_and_validate 单测（对齐 ticker_合并数据并校验完整标的.py，Dify DSL v2 迁移）。

覆盖：合并 infer/split 两路 + 完整标的正则校验(isFull) + 前导零副本 +
市场词过滤 + 期货合约日期规整 + 异常输入兜底。
"""
from __future__ import annotations

from app.subgraphs.ticker.tools import FULL_CODE_REGEX, MARKET_WORDS, merge_and_validate


def test_merges_infer_and_split_sources_deduped() -> None:
    infer = {"贵州茅台": ["600519.SH", "贵州茅台"]}
    split = {"贵州茅台": ["贵州茅台", "600519.SH"]}
    out = merge_and_validate(infer, split, {})
    assert len(out) == 1
    item = out[0]
    assert item["orgStr"] == "贵州茅台"
    keywords = [k["keyword"] for k in item["keywords"]]
    # 去重：600519.SH / 贵州茅台 各只出现一次
    assert keywords.count("600519.SH") == 1
    assert keywords.count("贵州茅台") == 1


def test_full_code_marks_is_full_true() -> None:
    out = merge_and_validate({"茅台": ["600519.SH"]}, {}, {})
    kw = out[0]["keywords"][0]
    assert kw["keyword"] == "600519.SH"
    assert kw["isFull"] is True


def test_non_full_keyword_marks_is_full_false() -> None:
    out = merge_and_validate({}, {"茅台": ["贵州茅台"]}, {})
    kw = out[0]["keywords"][0]
    assert kw["isFull"] is False


def test_full_code_with_leading_zero_gets_stripped_duplicate() -> None:
    out = merge_and_validate({"腾讯": ["00700.HK"]}, {}, {})
    keywords = out[0]["keywords"]
    kws = {k["keyword"]: k for k in keywords}
    assert "00700.HK" in kws
    assert "700.HK" in kws
    assert kws["00700.HK"]["isFull"] is True
    assert kws["700.HK"]["isFull"] is True
    # 前导零副本与原 keyword 共享同一个 id（对齐 JS 实现）
    assert kws["00700.HK"]["id"] == kws["700.HK"]["id"]


def test_full_code_without_leading_zero_no_duplicate() -> None:
    """代码本身无前导零 → 不追加去零副本（但 orgStr 本身仍作为兜底 keyword 追加）。"""
    out = merge_and_validate({"茅台": ["600519.SH"]}, {}, {})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert keywords.count("600519.SH") == 1
    assert keywords == ["600519.SH", "茅台"]


def test_market_words_filtered_out() -> None:
    out = merge_and_validate({}, {"A股中国平安": ["A股", "中国平安"]}, {})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert "A股" not in keywords
    assert "中国平安" in keywords


def test_market_words_constant_contains_expected_entries() -> None:
    assert "港股" in MARKET_WORDS
    assert "美股" in MARKET_WORDS
    assert "科创板" in MARKET_WORDS


def test_org_str_appended_as_fallback_keyword_when_not_present() -> None:
    out = merge_and_validate({"神秘标的XYZ": []}, {}, {})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert "神秘标的XYZ" in keywords


def test_futures_date_name_normalized_when_ins_family_future() -> None:
    """`0109沪铜`（日期+名称）+ insFamily=FUTURE → 追加规整后的 `沪铜0109`。"""
    out = merge_and_validate({}, {"0109沪铜": ["沪铜", "0109"]}, {"0109沪铜": "FUTURE"})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert "沪铜0109" in keywords


def test_futures_date_normalize_skipped_when_not_future_type() -> None:
    """同样的日期+名称模式，但 insFamily 不是 FUTURE → 不追加规整 keyword。"""
    out = merge_and_validate({}, {"0109沪铜": ["沪铜", "0109"]}, {"0109沪铜": "EQUITY"})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert "沪铜0109" not in keywords


def test_nested_list_in_infer_codes_flattened() -> None:
    """infer_codes 的 value 元素本身也可能是嵌套 list（保守兼容 LLM 输出格式抖动）。"""
    out = merge_and_validate({"贵州茅台": [["600519.SH", "贵州茅台"]]}, {}, {})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert "600519.SH" in keywords
    assert "贵州茅台" in keywords


def test_invalid_json_string_inputs_return_empty_result() -> None:
    assert merge_and_validate("not json", "not json", "not json") == []


def test_dict_input_used_directly_without_json_parse() -> None:
    out = merge_and_validate({"茅台": ["600519.SH"]}, {}, {})
    assert out[0]["orgStr"] == "茅台"


def test_markdown_fenced_json_string_stripped_before_parse() -> None:
    infer = '```json\n{"茅台": ["600519.SH"]}\n```'
    out = merge_and_validate(infer, {}, {})
    assert out[0]["orgStr"] == "茅台"
    assert out[0]["keywords"][0]["keyword"] == "600519.SH"


def test_full_code_regex_matches_known_exchange_suffixes() -> None:
    assert FULL_CODE_REGEX.search("600519.SH")
    assert FULL_CODE_REGEX.search("0700.HK")
    assert FULL_CODE_REGEX.search("AAPL.O")
    assert not FULL_CODE_REGEX.search("600519")
    assert not FULL_CODE_REGEX.search("贵州茅台")


def test_empty_infer_and_split_returns_empty_list() -> None:
    assert merge_and_validate({}, {}, {}) == []


def test_none_value_in_keyword_source_filtered() -> None:
    out = merge_and_validate({"茅台": [None, "600519.SH", ""]}, {}, {})
    keywords = [k["keyword"] for k in out[0]["keywords"]]
    assert None not in keywords
    assert "" not in keywords
    assert "600519.SH" in keywords
