"""app/domain/numerals.py：序号与中文数字解析的唯一实现。"""
from __future__ import annotations

import pytest

from app.domain.numerals import chinese_int, ordinal_int, require_ordinal


@pytest.mark.parametrize(("text", "expected"), [
    ("一", 1), ("十", 10), ("十二", 12), ("二十", 20), ("二十三", 23), ("两百", 200),
    ("一百零五", 105), ("两千", 2000), ("三千五百", 3500), ("〇", 0), ("零", 0),
])
def test_chinese_int(text: str, expected: int) -> None:
    assert chinese_int(text) == expected


@pytest.mark.parametrize("text", ["12", "三a", "万", "-"])
def test_chinese_int_rejects_non_chinese(text: str) -> None:
    """期限 / 金额只接受纯中文数字；阿拉伯数字由调用方正则另行处理。"""
    assert chinese_int(text) is None


@pytest.mark.parametrize(("token", "expected"), [
    ("3", 3), ("+3", 3), ("-2", -2), ("12", 12), ("三", 3), ("十一", 11), ("两", 2),
])
def test_ordinal_int(token: str, expected: int) -> None:
    assert ordinal_int(token) == expected


def test_ordinal_int_returns_none_for_unparseable() -> None:
    assert ordinal_int("第") is None


def test_require_ordinal_raises_for_unparseable() -> None:
    assert require_ordinal("十五") == 15
    with pytest.raises(ValueError):
        require_ordinal("x")
