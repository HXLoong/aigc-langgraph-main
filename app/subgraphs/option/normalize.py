"""option 询价链路归一化（OPT-07 下沉：LLM 原文片段 → 后端规范值）。

原先写在 `app/prompts/option/extract_inquiry.md` 里、交给 LLM 执行的
tenor / 百分号 / 名义本金 / 参与率归一化与 "/" 多值笛卡尔积展开，全部下沉到本模块；
LLM 只负责逐字抽取原文片段（`OptionInquiryRawItem`）。

- tenor: "1年" → "12M"（年 × 12，取整月校验）、"1个月"/"一个月" → "1M"、"半年" → "6M"、
  小写 m 归一化、纯数字补 M；小数月（"1.5M"）非法 → None
- strikePercentage: "80%" → 80.0、"平值"/"平直" → 100.0、"/" 多值展开
- notionalAmount: "100万"/"1W"/"1kw"/"1千万"/"1亿"/"两千万" → 数字字符串
  （单位口径按询价提示词：1kw = 1万；下单链路此前未单独定义 kw，统一此口径）
- participationRate: "90%" / "参与率: 90%" → 90.0

名义本金相关基础函数同时供 `place_params.py`（下单链路）复用。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.extraction.fields import EvidenceError
from app.subgraphs.option.models import OptionInquiryRawItem

# ============================================================
# 名义本金（下单链路共用）
# ============================================================

#: 中文数字（≤ 万级组合，如 三千五百 → 3500）
_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

#: 数字 + 单位（千万 / kw / 亿 / 万 / w / e）
_DIGIT_AMOUNT_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(千万|[Kk][Ww]|亿|万|[Ww]|[Ee])(?![A-Za-z])"
)
#: 中文数字 + 万 / 亿
_CN_AMOUNT_RE = re.compile(r"([零〇一二两三四五六七八九十百千]{1,8})(万|亿)")
_PLAIN_DIGITS_RE = re.compile(r"^\d+$")
_AMOUNT_MULTIPLIERS = {
    "千万": 10_000_000,
    "kw": 10_000,
    "万": 10_000,
    "w": 10_000,
    "亿": 100_000_000,
    "e": 100_000_000,
}


def _cn_number(text: str) -> int | None:
    """解析中文数字（≤ 千级组合），如 两千 → 2000、三千五百 → 3500。"""
    total = 0
    current = 0
    for char in text:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        elif char == "千":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    return total + current


def _format_amount(value: float) -> str:
    return str(int(round(value)))


def normalize_notional(text: str | None, *, allow_plain_digits: bool = False) -> str | None:
    """名义本金："XX万 / XXW / XXkw / XX亿 / XXE / 两千万" → 数字字符串。

    `allow_plain_digits`：询价链路 LLM 片段可能是纯数字（如 "1000000"），置 True；
    下单链路在整段原文里搜索，纯数字更可能是标的代码（600519），保持 False。
    """
    value = (text or "").strip()
    if not value:
        return None
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
# 期限
# ============================================================

_TENOR_YEAR_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[Yy年]$")
_TENOR_MONTH_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:个?月|[Mm])$")
_TENOR_PLAIN_RE = re.compile(r"^(\d+(?:\.\d+)?)$")
_TENOR_CN_YEAR_RE = re.compile(r"^([零〇一二两三四五六七八九十]+)年$")
_TENOR_CN_MONTH_RE = re.compile(r"^([零〇一二两三四五六七八九十]+)个?月$")


def _months_to_tenor(months: float) -> str | None:
    """正整数月份 → "XM"；小数月 / 非正数非法（提示词原文规约）。"""
    if months <= 0 or months != int(months):
        return None
    return f"{int(months)}M"


def normalize_tenor(text: str | None) -> str | None:
    """期限原文片段 → "XM"；无法解析 → None。"""
    value = (text or "").strip()
    if not value:
        return None
    if value == "半年":
        return "6M"
    cn_year = _TENOR_CN_YEAR_RE.fullmatch(value)
    if cn_year:
        number = _cn_number(cn_year.group(1))
        return _months_to_tenor(number * 12) if number else None
    cn_month = _TENOR_CN_MONTH_RE.fullmatch(value)
    if cn_month:
        number = _cn_number(cn_month.group(1))
        return _months_to_tenor(number) if number else None
    year = _TENOR_YEAR_RE.fullmatch(value)
    if year:
        return _months_to_tenor(float(year.group(1)) * 12)
    month = _TENOR_MONTH_RE.fullmatch(value)
    if month:
        return _months_to_tenor(float(month.group(1)))
    plain = _TENOR_PLAIN_RE.fullmatch(value)
    if plain:
        return _months_to_tenor(float(plain.group(1)))
    return None


# ============================================================
# 执行价 / 参与率
# ============================================================

_NUMBER_PERCENT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*%?$")
_PING_KEYWORDS = ("平值", "平直")
_PARTICIPATION_LABEL_RE = re.compile(r"^(?:参与率|参与比例)\s*[:：]?\s*")


def normalize_strike(text: str | None) -> float | None:
    """执行价原文片段 → 数字（去 %）；"平值"/"平直" → 100.0；无法解析 → None。"""
    value = (text or "").strip()
    if not value:
        return None
    if value in _PING_KEYWORDS:
        return 100.0
    match = _NUMBER_PERCENT_RE.fullmatch(value)
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
    if text.lower() == "call" or text == "看涨" or compound_call_strike(text) is not None:
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
