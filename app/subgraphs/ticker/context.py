"""订单上下文中的确定性文本匹配，仅作用于标的识别副本。"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple


class ShortnameSpan(NamedTuple):
    start: int
    end: int
    shortname: str


_COUNTERPARTY_LABEL = re.compile(r"(?:交易对手|对手|账号)\s*[:：]?\s*$")
TRAILING_PUNCTUATION = re.compile(r"[\s。.!！?？,，;；、…]*")


def match_counterparty_shortnames(
    text: str, shortnames: Sequence[str],
) -> list[ShortnameSpan]:
    """完整名称匹配；纯数字须有对手标签，被更长名称包含的匹配不算独立对手。"""
    matches = []
    for name in set(shortnames):
        if not name.strip():
            continue
        for match in re.finditer(re.escape(name), text):
            start, end = match.span()
            labeled = _COUNTERPARTY_LABEL.search(text[:start]) is not None
            left_boundary = start == 0 or not re.match(r"\w", text[start - 1])
            right_boundary = end == len(text) or not re.match(r"\w", text[end])
            if name.isdigit() and re.match(r"(?:\.[A-Za-z0-9]|[,，]\d{3})", text[end:]):
                right_boundary = False
            if (labeled or left_boundary) and right_boundary and (not name.isdigit() or labeled):
                matches.append(ShortnameSpan(start, end, name))
    return sorted(
        (match for match in matches if not any(
            other.start <= match.start and match.end <= other.end
            and len(other.shortname) > len(match.shortname)
            for other in matches
        )),
        key=lambda match: (match.start, match.end),
    )


_NUMBER = re.compile(r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?")
_QUANTITY_UNIT = re.compile(
    r"\s*(?:万|千|亿|[kKwW])?\s*(?:股(?!指|票|份)|手|张|份|lots?)(?![A-Za-z])", re.I,
)
_PRICE_UNIT = re.compile(r"\s*(?:美元|港元|人民币|元|块|USD|HKD|CNY|RMB)(?![A-Za-z])", re.I)
_VALUE_LABEL = re.compile(
    r"(?:股份数量|委托数量|数量|股数|手数|"
    r"(?<!不设)(?<!不)(?<!无)限价(?:委托)?|(?<!不)(?<!无)限定价格|"
    r"(?<!不)(?<!无)(?<!限定)(?<!限制)(?:委托)?价格|均价|均價|"
    r"(?:POV)?比例|参与率|跟量|占比|POV|@)\s*[:：=]?\s*$", re.I,
)
_TARGET_LABEL = re.compile(r"(?:标的(?:代码)?|证券代码|股票代码|代码)\s*[:：=]?\s*$")
_SUFFIX_CODE = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z0-9]+\.[A-Za-z][A-Za-z0-9]*(?![A-Za-z0-9_.])")
_PERCENT = re.compile(r"\s*[%％]")


def mask_order_context(text: str, shortnames: Sequence[str] = ()) -> str:
    """分词前按原字符位置遮蔽明确的订单值和完整对手名称，保持文本长度。"""
    spans = [
        (match.start, match.end) for match in match_counterparty_shortnames(text, shortnames)
        if not _TARGET_LABEL.search(text[:match.start])
    ]
    protected = [match.span() for match in _SUFFIX_CODE.finditer(text)]
    for match in _NUMBER.finditer(text):
        start, end = match.span()
        prefix, suffix = text[:start], text[end:]
        if _TARGET_LABEL.search(prefix) or any(left <= start < right for left, right in protected):
            continue
        label = _VALUE_LABEL.search(prefix)
        unit = _QUANTITY_UNIT.match(suffix) or _PRICE_UNIT.match(suffix) or _PERCENT.match(suffix)
        if label or unit:
            spans.append((label.start() if label else start, end + unit.end() if unit else end))
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)
