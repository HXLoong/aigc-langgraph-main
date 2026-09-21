"""平仓执行方式短语归一化；只接受唯一、明确且有本轮原文依据的方式。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

from app.extraction.fast_execution import FAST_EXECUTION_PHRASES
from app.observability.privacy import mask_sensitive
from app.subgraphs.close.models import ClosePriceType
from app.subgraphs.close.order_id import CONTRACT_CODE_RE, ORDER_ID_RE

_ALIASES: dict[ClosePriceType, tuple[str, ...]] = {
    "市价单": ("市价", "市价单", "market", "mkt", "不用跟量", "不跟量", "不要跟量"),
    "限价单": ("限价", "限价单", "limit", "lmt"),
    "POV": ("pov", "跟量", "正常挂单"),
    "TWAP": ("twap", "时间加权", "时间均价", "均匀执行"),
}
_BY_ALIAS = {alias.casefold(): value for value, aliases in _ALIASES.items() for alias in aliases}
# 最大跟量意图仍参与执行方式的否定、条件检查，避免被裁剪成普通“跟量”。
_TOKENS = "|".join(
    re.escape(alias) for alias in sorted((*_BY_ALIAS, *FAST_EXECUTION_PHRASES), key=len, reverse=True)
)
_PREFIX = r"(?:按|以|用|采用|使用)"
_PHRASE = re.compile(rf"(?:{_PREFIX})?(?P<mode>{_TOKENS})(?:(?:进行|来)?(?:下单|平仓|执行|委托))?")
# ASCII boundaries prevent a contract or arbitrary English word becoming a mode.
_MODE = re.compile(rf"(?<![a-z_])(?:{_TOKENS})(?![a-z_])")
_NEGATED_PREFIX = re.compile(
    r"(?:不|别|勿|非|禁止|无需|取消)[^，,；;。\n]{0,8}$|\b(?:not|no|never|don't)\s*$"
)
_NEGATED_SUFFIX = re.compile(
    r"\s*(?:下单|平仓|执行|委托)?\s*(?:不要(?!\s*跟量)|不行|不可以|不做|不执行)"
)
_CONDITIONAL = re.compile(
    r"[?？]|是否|能否|可否|如果|假如|(?:成交|成功|不行|不成).{0,8}(?:后|再|就)"
    r"|(?:等|到)[^，,；;。\n]*再|[吗么嘛](?:[。！!\s]|$)|\bif\b"
)
_CHOICE = re.compile(r"或者|或|还是|任选|都行|都可以|二选一|随便|\b(?:or|either)\b")
_NO_FOLLOW = frozenset({"不用跟量", "不跟量", "不要跟量"})
_ALGORITHMS = frozenset({"POV", "TWAP"})


class CloseOrderTypeNormalizationError(ValueError):
    """可定位的执行方式识别错误；不泄露整段输入或后端数据。"""

    def __init__(
        self,
        candidate: str | None,
        reason: Literal["unsupported", "negated", "conflicting"],
    ) -> None:
        self.reason = reason
        # Existing field-mask settings must also apply when embedding a value in an exception.
        detail = mask_sensitive({"closeOrderType": {"value": candidate}})["closeOrderType"]
        value = detail.get("value") if isinstance(detail, dict) else detail
        preview = str(value)[:160] if value is not None else None
        super().__init__(
            f"closeOrderType: reason={reason}; candidate={preview!r}; "
            "supported=市价单/限价单/POV/TWAP"
        )


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def is_fast_execution_phrase(candidate: str) -> bool:
    """兼容模型将最大跟量意图短语放进执行方式候选的情况。"""
    match = _PHRASE.fullmatch(re.sub(r"\s+", "", _text(candidate)))
    return match is not None and match["mode"] in FAST_EXECUTION_PHRASES


def normalize_close_order_type(
    candidate: str | None,
    *,
    order_texts: Sequence[str],
    inferred: ClosePriceType | None = None,
) -> ClosePriceType | None:
    """候选完整匹配；订单片段检查阻止模型裁剪否定、条件和冲突关系。"""
    matched: list[tuple[str, ClosePriceType]] = []
    for original in order_texts:
        text = _text(ORDER_ID_RE.sub(" ", CONTRACT_CODE_RE.sub(" ", original)))
        modes = list(_MODE.finditer(text))
        if modes and (_CONDITIONAL.search(text) or _CHOICE.search(text)):
            raise CloseOrderTypeNormalizationError(candidate, "conflicting")
        for mode in modes:
            if _NEGATED_PREFIX.search(text[: mode.start()]) or _NEGATED_SUFFIX.match(
                text[mode.end() :]
            ):
                raise CloseOrderTypeNormalizationError(candidate, "negated")
            if mode[0] in _BY_ALIAS:
                matched.append((mode[0], _BY_ALIAS[mode[0]]))

    # Existing business exception: “不用跟量，正常挂单” means 市价单, not POV.
    no_follow = any(alias in _NO_FOLLOW for alias, _ in matched)
    modes_in_order = {value for alias, value in matched if not (no_follow and alias == "正常挂单")}
    algorithms = modes_in_order & _ALGORITHMS
    prices = modes_in_order - _ALGORITHMS
    if len(algorithms) > 1 or len(prices) > 1:
        raise CloseOrderTypeNormalizationError(candidate, "conflicting")

    normalized = inferred
    if candidate is not None:
        phrase = re.sub(r"\s+", "", _text(candidate))
        match = _PHRASE.fullmatch(phrase)
        if match is None:
            raise CloseOrderTypeNormalizationError(candidate, "unsupported")
        if match["mode"] in FAST_EXECUTION_PHRASES:
            return None
        if not matched:
            raise CloseOrderTypeNormalizationError(candidate, "unsupported")
        normalized = _BY_ALIAS[match["mode"]]
    if no_follow and normalized == "POV":
        raise CloseOrderTypeNormalizationError(candidate, "negated")
    # An algorithm may have a limit price; a price candidate cannot replace that algorithm.
    if normalized is not None and (
        (algorithms and normalized not in algorithms)
        or (normalized not in _ALGORITHMS and prices and normalized not in prices)
    ):
        raise CloseOrderTypeNormalizationError(candidate, "conflicting")
    return normalized if candidate is not None else None
