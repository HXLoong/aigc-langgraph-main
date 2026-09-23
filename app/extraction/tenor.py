"""期权期限的唯一换算规则；原文与出站参数分离。"""
from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from typing import Any

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


_TENOR_YEAR_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[Yy年]$")
_TENOR_MONTH_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:个?月|[Mm])$")
_TENOR_PLAIN_RE = re.compile(r"^(\d+(?:\.\d+)?)$")
_TENOR_CN_YEAR_RE = re.compile(r"^([零〇一二两三四五六七八九十]+)年$")
_TENOR_CN_MONTH_RE = re.compile(r"^([零〇一二两三四五六七八九十]+)个?月$")


def _months_to_tenor(months: Decimal | int) -> str | None:
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
        return _months_to_tenor(Decimal(year.group(1)) * 12)
    month = _TENOR_MONTH_RE.fullmatch(value)
    if month:
        return _months_to_tenor(Decimal(month.group(1)))
    plain = _TENOR_PLAIN_RE.fullmatch(value)
    if plain:
        return _months_to_tenor(Decimal(plain.group(1)))
    return None


class TenorError(ValueError):
    """提供了期限，但无法确定正整数月份；不能回填旧值或静默丢弃。"""


def monthly_tenor(value: Any) -> str | None:
    if value is None or value == "":
        return None
    result = normalize_tenor(value) if isinstance(value, str) else None
    if result is None:
        raise TenorError("期限无法转换为正整数月份，请明确期限后重新提交（例如3M、半年或1年）。")
    return result


def normalize_request_tenors(payload: dict[str, Any]) -> dict[str, Any]:
    """只处理业务期限，保留 rawContent/quoteContent 与调用方原对象。"""
    result = deepcopy(payload)
    for order in result.get("orderList") or []:
        if isinstance(order, dict) and "tenor" in order:
            order["tenor"] = monthly_tenor(order["tenor"])
    rfq = result.get("optionRfq")
    if isinstance(rfq, dict) and rfq.get("tenor") is not None:
        if not isinstance(rfq["tenor"], list):
            raise TenorError("询价期限必须为月份列表，请明确期限后重新提交。")
        tenors = [monthly_tenor(value) for value in rfq["tenor"]]
        if any(value is None for value in tenors):
            raise TenorError("询价期限列表包含空值，请明确所有期限后重新提交。")
        rfq["tenor"] = tenors
    return result
