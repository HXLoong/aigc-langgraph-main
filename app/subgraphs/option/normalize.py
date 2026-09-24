"""option 询价链路归一化（OPT-07 下沉：LLM 原文片段 → 后端规范值）。

原先写在 `app/prompts/option/extract_inquiry.md` 里、交给 LLM 执行的
tenor / 百分号 / 名义本金 / 参与率归一化与 "/" 多值笛卡尔积展开，全部下沉到本模块；
LLM 只负责逐字抽取原文片段（`OptionInquiryRawItem`）。

- tenor: "1年" → "12M"（年 × 12，取整月校验）、"1个月"/"一个月" → "1M"、"半年" → "6M"、
  小写 m 归一化、纯数字补 M；小数月（"1.5M"）非法 → None
- strikePercentage: "80%" → 80.0、"平值"/"平直" → 100.0、"/" 多值展开
- notionalAmount: "100万"/"1W"/"1kw"/"1千万"/"1亿"/"两千万" → 数字字符串
  （业务裁决：1kw = 1000 万，询价 / 下单 / 平仓统一此口径）
- participationRate: "90%" / "参与率: 90%" → 90.0

名义本金相关基础函数同时供 `place_params.py`（下单链路）复用。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.extraction.fields import EvidenceError
from app.extraction.tenor import _cn_number as _cn_number
from app.extraction.tenor import normalize_tenor
from app.subgraphs.option.models import OptionInquiryRawItem

# ============================================================
# 名义本金（下单链路共用）
# ============================================================

#: 数字 + 单位（千万 / kw / 亿 / 万 / w / e）
_DIGIT_AMOUNT_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(千万|[Kk][Ww]|亿|万|[Ww]|[Ee])(?![A-Za-z])"
)
#: 中文数字 + 万 / 亿
_CN_AMOUNT_RE = re.compile(r"([零〇一二两三四五六七八九十百千]{1,8})(万|亿)")
_PLAIN_DIGITS_RE = re.compile(r"^\d+$")
_AMOUNT_MULTIPLIERS = {
    "千万": 10_000_000,
    "kw": 10_000_000,  # 业务裁决：1kw = 1000 万（与平仓链路一致）
    "万": 10_000,
    "w": 10_000,
    "亿": 100_000_000,
    "e": 100_000_000,
}


def _format_amount(value: float) -> str:
    return str(int(round(value)))


def normalize_notional(
    text: str | None, *, allow_plain_digits: bool = False, require_unique: bool = False,
) -> str | None:
    """名义本金："XX万 / XXW / XXkw / XX亿 / XXE / 两千万" → 数字字符串。

    `allow_plain_digits`：询价链路 LLM 片段可能是纯数字（如 "1000000"），置 True；
    下单链路在整段原文里搜索，纯数字更可能是标的代码（600519），保持 False。
    """
    value = (text or "").strip()
    if not value:
        return None
    if require_unique:
        amounts = {normalize_notional(match[0])
                   for pattern in (_DIGIT_AMOUNT_RE, _CN_AMOUNT_RE)
                   for match in pattern.finditer(value)} - {None}
        if len(amounts) > 1:
            raise ValueError("同一订单出现多个名义本金，请明确每笔订单的金额。")
    if allow_plain_digits and _PLAIN_DIGITS_RE.fullmatch(value):
        return value
    match = _DIGIT_AMOUNT_RE.search(value)
    if match:
        return _format_amount(float(match.group(1)) * _AMOUNT_MULTIPLIERS[match.group(2).lower()])
    cn_match = _CN_AMOUNT_RE.search(value)
    if cn_match:
        number = _cn_number(cn_match.group(1))
        if number:
            unit = 100_000_000 if cn_match.group(2) == "亿" else 10_000
            return _format_amount(number * unit)
    return None


# ============================================================
# 执行价 / 参与率
# ============================================================

_NUMBER_PERCENT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*%?$")
_CALL_STRIKE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*call", re.IGNORECASE)
_PING_KEYWORDS = ("平值", "平直")
_PARTICIPATION_LABEL_RE = re.compile(r"^(?:参与率|参与比例)\s*[:：]?\s*")


def normalize_strike(text: str | None) -> float | None:
    """执行价原文片段 → 数字（去 %）；"平值"/"平直" → 100.0；无法解析 → None。"""
    value = (text or "").strip()
    if not value:
        return None
    if value in _PING_KEYWORDS:
        return 100.0
    match = _NUMBER_PERCENT_RE.fullmatch(value) or _CALL_STRIKE_RE.fullmatch(value)
    return float(match.group(1)) if match else None


def normalize_participation(text: str | None) -> float | None:
    """参与率原文片段（可带 "参与率" 标签与 %）→ 数字；无法解析 → None。"""
    value = _PARTICIPATION_LABEL_RE.sub("", (text or "").strip())
    match = _NUMBER_PERCENT_RE.fullmatch(value)
    return float(match.group(1)) if match else None


# ============================================================
# "/" 多值展开
# ============================================================


def _split_values(text: str | None) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    return [part.strip() for part in value.split("/")]


def split_tenors(text: str | None) -> list[str | None]:
    """tenor 片段 → 归一化列表（"/" 展开）；空片段 → [None]，无法解析的项 → None。"""
    parts = _split_values(text)
    if not parts:
        return [None]
    return [normalize_tenor(part) for part in parts]


def split_strikes(text: str | None) -> list[float | None]:
    """执行价片段 → 归一化列表（"/" 展开）；空片段 → [None]，无法解析的项 → None。"""
    parts = _split_values(text)
    if not parts:
        return [None]
    return [normalize_strike(part) for part in parts]


_COMPOUND_CALL = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%?\s*(?:call|看涨)", re.I)


def compound_call_strike(value: str | None) -> float | None:
    """完整匹配执行价与看涨类型的复合原文，不从任意文本搜索数字。"""
    match = _COMPOUND_CALL.fullmatch((value or "").strip())
    return float(match[1]) if match else None


def normalize_option_type(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if compound_call_strike(text) is not None:
        return "欧式看涨"
    # 「看涨期权」「雪球期权」等带通称后缀的写法与枚举同义；不支持的类型原样返回，由调用方拒绝
    text = re.sub(r"\s*期权$", "", text)
    if text.lower() == "call" or text in {"看涨", "欧式看涨"}:
        return "欧式看涨"
    return text


def expand_inquiry_items(items: Sequence[OptionInquiryRawItem]) -> list[dict[str, Any]]:
    """LLM 原文片段条目 → canonical partial dict 列表。

    按 (tenor 值个数) × (strikePercentage 值个数) 笛卡尔积展开（提示词旧规约：
    "1/3M 100/103%" → 4 条），其余字段原样透传。
    """
    expanded: list[dict[str, Any]] = []
    for item in items:
        tenors = split_tenors(item.tenor)
        strikes = split_strikes(item.strike_percentage)
        compound_strike = compound_call_strike(item.option_type)
        if compound_strike is not None:
            if not (item.strike_percentage or "").strip():
                strikes = [compound_strike]
            elif any(strike != compound_strike for strike in strikes):
                raise EvidenceError("复合期权表达与显式执行价冲突，请明确执行价。")
        notional = normalize_notional(item.notional_amount, allow_plain_digits=True)
        participation = normalize_participation(item.participation_rate)
        for tenor in tenors:
            for strike in strikes:
                expanded.append({
                    "order_id": item.order_id,
                    "stock_code": item.stock_code,
                    "option_type": normalize_option_type(item.option_type),
                    "tenor": tenor,
                    "strike_percentage": strike,
                    "notional_amount": notional,
                    "participation_rate": participation,
                    "short_name": item.short_name,
                })
    return expanded


__all__ = [
    "compound_call_strike",
    "expand_inquiry_items",
    "normalize_notional",
    "normalize_participation",
    "normalize_strike",
    "normalize_tenor",
    "split_strikes",
    "split_tenors",
]
