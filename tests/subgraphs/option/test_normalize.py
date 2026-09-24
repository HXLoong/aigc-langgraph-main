"""option 询价链路归一化单元测试（OPT-07 下沉：tenor / 百分号 / 名义本金等）。

这些规约原先写在 `app/prompts/option/extract_inquiry.md` 里交给 LLM 执行，
代码侧零校验；现在 LLM 只输出原文片段，归一化由 `option/normalize.py` 确定性完成。
"""

from __future__ import annotations

import pytest

from app.extraction.fields import EvidenceError
from app.subgraphs.option.models import OptionInquiryRawItem
from app.subgraphs.option.normalize import (
    expand_inquiry_items,
    normalize_notional,
    normalize_participation,
    normalize_strike,
    normalize_tenor,
    split_strikes,
    split_tenors,
)


class TestNormalizeTenor:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1M", "1M"),
            ("12M", "12M"),
            ("1m", "1M"),
            ("1个月", "1M"),
            ("1 个月", "1M"),
            ("一个月", "1M"),
            ("两个月", "2M"),
            ("三个月", "3M"),
            ("3个月", "3M"),
            ("6个月", "6M"),
            ("半年", "6M"),
            ("1Y", "12M"),
            ("1y", "12M"),
            ("1年", "12M"),
            ("一年", "12M"),
            ("两年", "24M"),
            ("三年", "36M"),
            ("1.5年", "18M"),
            ("0.5年", "6M"),
            ("1", "1M"),
            ("12", "12M"),
            (None, None),
            ("", None),
            ("1.5M", None),
            ("0M", None),
            ("abc", None),
        ],
    )
    def test_normalize(self, raw: str | None, expected: str | None) -> None:
        assert normalize_tenor(raw) == expected


class TestSplitTenors:
    def test_single_value(self) -> None:
        assert split_tenors("1M") == ["1M"]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1M/3M", ["1M", "3M"]),
            ("1/2M", ["1M", "2M"]),
            ("2/6M", ["2M", "6M"]),
            ("1/3M", ["1M", "3M"]),
        ],
    )
    def test_slash_expansion(self, raw: str, expected: list[str]) -> None:
        assert split_tenors(raw) == expected

    def test_empty_stays_single_none(self) -> None:
        assert split_tenors(None) == [None]
        assert split_tenors("") == [None]

    def test_invalid_part_kept_as_none(self) -> None:
        assert split_tenors("1M/xx") == ["1M", None]


class TestNormalizeStrike:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("100%", 100.0),
            ("95%", 95.0),
            ("103.5%", 103.5),
            ("100", 100.0),
            ("80", 80.0),
            ("平值", 100.0),
            ("平直", 100.0),
            (None, None),
            ("", None),
            ("abc", None),
        ],
    )
    def test_normalize(self, raw: str | None, expected: float | None) -> None:
        assert normalize_strike(raw) == expected

    @pytest.mark.parametrize(
        ("fragment", "expected"),
        [("80call", 80.0), ("103.5% CALL", 103.5), ("100put", None), ("callback", None)],
    )
    def test_call_shorthand(self, fragment: str, expected: float | None) -> None:
        assert normalize_strike(fragment) == expected


class TestSplitStrikes:
    def test_single_value(self) -> None:
        assert split_strikes("80%") == [80.0]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("100/103%", [100.0, 103.0]),
            ("100%/103%", [100.0, 103.0]),
            ("70/103", [70.0, 103.0]),
        ],
    )
    def test_slash_expansion(self, raw: str, expected: list[float]) -> None:
        assert split_strikes(raw) == expected

    def test_empty_stays_single_none(self) -> None:
        assert split_strikes(None) == [None]
        assert split_strikes("") == [None]


class TestNormalizeNotional:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("100万", "1000000"),
            ("1W", "10000"),
            ("1w", "10000"),
            ("1000w", "10000000"),
            ("1000W", "10000000"),
            ("1KW", "10000"),
            ("1kw", "10000"),
            ("1千万", "10000000"),
            ("1亿", "100000000"),
            ("1E", "100000000"),
            ("1e", "100000000"),
            ("两千万", "20000000"),
            ("三千万", "30000000"),
            (None, None),
            ("", None),
            ("abc", None),
        ],
    )
    def test_normalize(self, raw: str | None, expected: str | None) -> None:
        assert normalize_notional(raw) == expected

    def test_plain_digits_rejected_by_default(self) -> None:
        """默认不接受纯数字：下单链路里 6 位数字更可能是标的代码。"""
        assert normalize_notional("1000000") is None

    def test_plain_digits_opt_in(self) -> None:
        assert normalize_notional("1000000", allow_plain_digits=True) == "1000000"


class TestNormalizeParticipation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("90%", 90.0),
            ("90", 90.0),
            ("参与率: 90%", 90.0),
            ("参与比例 80%", 80.0),
            (None, None),
            ("", None),
            ("abc", None),
        ],
    )
    def test_normalize(self, raw: str | None, expected: float | None) -> None:
        assert normalize_participation(raw) == expected


class TestExpandInquiryItems:
    @pytest.mark.parametrize("fragment", ["100call", "100 CALL", "100%Call", "100 % call"])
    def test_call_shorthand_preserves_type_and_strike(self, fragment: str) -> None:
        item = OptionInquiryRawItem(stockCode="宁德时代", optionType=fragment, tenor="1M")
        result = expand_inquiry_items([item])[0]
        assert result["option_type"] == "欧式看涨"
        assert result["strike_percentage"] == 100.0

    def test_call_shorthand_rejects_conflicting_explicit_strike(self) -> None:
        item = OptionInquiryRawItem(optionType="100call", strikePercentage="80%")
        # 保留本地已验收的冲突保护，不让两个相互矛盾的执行价静默通过。
        with pytest.raises(EvidenceError, match="执行价冲突"):
            expand_inquiry_items([item])

    def test_normalizes_all_fields(self) -> None:
        items = [OptionInquiryRawItem(
            stockCode="贵州茅台", optionType="欧式看涨", tenor="1个月",
            strikePercentage="80%", notionalAmount="100万", participationRate="90%",
        )]
        assert expand_inquiry_items(items) == [{
            "order_id": None, "stock_code": "贵州茅台", "option_type": "欧式看涨",
            "tenor": "1M", "strike_percentage": 80.0, "notional_amount": "1000000",
            "participation_rate": 90.0, "short_name": None,
        }]

    def test_cartesian_expansion_of_slash_values(self) -> None:
        items = [OptionInquiryRawItem(stockCode="茅台", tenor="1/3M", strikePercentage="100/103%")]
        expanded = expand_inquiry_items(items)
        assert [(i["tenor"], i["strike_percentage"]) for i in expanded] == [
            ("1M", 100.0), ("1M", 103.0), ("3M", 100.0), ("3M", 103.0),
        ]
        assert all(i["stock_code"] == "茅台" for i in expanded)

    def test_tenor_only_expansion(self) -> None:
        items = [OptionInquiryRawItem(tenor="1M/3M", strikePercentage="100%")]
        expanded = expand_inquiry_items(items)
        assert [(i["tenor"], i["strike_percentage"]) for i in expanded] == [
            ("1M", 100.0), ("3M", 100.0),
        ]

    def test_invalid_fragment_keeps_item_with_none(self) -> None:
        items = [OptionInquiryRawItem(stockCode="腾讯", tenor="1.5M")]
        expanded = expand_inquiry_items(items)
        assert len(expanded) == 1
        assert expanded[0]["tenor"] is None
        assert expanded[0]["stock_code"] == "腾讯"

    def test_empty_fragments_keep_single_item(self) -> None:
        items = [OptionInquiryRawItem(stockCode="腾讯")]
        expanded = expand_inquiry_items(items)
        assert len(expanded) == 1
        assert expanded[0]["tenor"] is None
        assert expanded[0]["strike_percentage"] is None
