"""最大跟量意图的公共规则；只判断标志，不选择算法或默认比例。"""
from __future__ import annotations

import re
import unicodedata

# 合并三个业务域已有的表达，避免各域维护不同的关键词与优先级。
FAST_EXECUTION_PHRASES = (
    "最大跟量", "拉满跟量", "全跟量", "大量跟量", "积极跟量", "尽快成交", "尽快",
    "儘快", "快点成交", "快点", "快速成交", "快速", "要快", "积极成交", "全力成交",
    "尽量成交",
)
_PHRASES = re.compile("|".join(
    re.escape(phrase) for phrase in sorted(FAST_EXECUTION_PHRASES, key=len, reverse=True)
))
_NEGATED_PREFIX = re.compile(
    r"(?:不|别|勿|非|禁止|无需|取消)[^，,；;。\n]{0,8}$|\b(?:not|no|never|don't)\s*$"
)
_NEGATED_SUFFIX = re.compile(
    r"\s*(?:下单|平仓|执行|委托)?\s*(?:不要|不行|不可以|不用|不做|不执行|不需要)"
)
_CONDITIONAL_OR_QUESTION = re.compile(
    r"[?？]|是否|能否|可否|如果|假如|什么|怎么|如何|(?:成交|成功|不行|不成).{0,8}(?:后|再|就)"
    r"|(?:等|到)[^，,；;。\n]*再|[吗么嘛](?:[。！!\s]|$)|\bif\b"
    r"|或者|还是|任选|都行|都可以|二选一|随便|\b(?:or|either)\b"
)
_EXPLICIT_POV_RATIO = re.compile(
    r"(?:pov|跟量(?:比例)?)\s*[:：]?\s*[+-]?[0-9]+(?:\.[0-9]+)?"
    r"(?![0-9.]|万|亿|股|手|w|k|e)", re.I,
)


def resolve_fast_execution(text: str, *, has_explicit_pov_ratio: bool = False) -> bool:
    """仅接收本笔订单的本轮证据；金额比例不视为 POV 比例。"""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    matches = list(_PHRASES.finditer(normalized))
    if not matches or _CONDITIONAL_OR_QUESTION.search(normalized):
        return False
    if any(
        _NEGATED_PREFIX.search(normalized[:match.start()])
        or _NEGATED_SUFFIX.match(normalized[match.end():])
        for match in matches
    ):
        return False
    if any(match[0] == "最大跟量" for match in matches):
        return True
    return not has_explicit_pov_ratio and not bool(_EXPLICIT_POV_RATIO.search(normalized))
