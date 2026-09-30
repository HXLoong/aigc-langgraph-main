"""按传输字段契约比较数值；仅用于评测，不改写业务参数。"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.request_cleaning import CLOSE_FIELDS, OPTION_FIELDS, SWAP_FIELDS

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def _field_kind(path: str, product: str | None) -> str | None:
    """只识别实际参数信封中的契约字段，不能按字段名全局放宽比较。"""
    normalized = re.sub(r"\[\d+\]", "[]", path)
    parent, _, field = normalized.rpartition(".")
    if parent in {"close_params.closeOrderList[]", "backend_request.closeOrderReqVO.closeOrderList[]"}:
        return CLOSE_FIELDS.get(field)
    if parent in {"place_params.orderList[]", "cancel_params.orderList[]", "confirm.orderList[]",
                  "backend_request.orderList[]"}:
        rules = {"option": OPTION_FIELDS, "swap": SWAP_FIELDS}.get(product or "", {})
        return rules.get(field)
    # 快速接口这些数组的元素是数字文本；标的、产品与期限仍严格比较。
    if product == "option" and parent == "backend_request.optionRfq" and field in {
        "strike[]", "knockInPrice[]", "knockOutPrice[]", "estimateMargin[]", "participateRate[]",
    }:
        return "numeric_text"
    return None


def _decimal(value: Any, *, percentage: bool) -> Decimal:
    """精确读取有限数值；百分号仅用于 Java 明确支持该格式的百分比字段。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("not a numeric scalar")
    text = str(value).strip()
    if percentage and text.endswith(("%", "％")):
        text = text[:-1].strip()
    if not _NUMBER.fullmatch(text):
        raise ValueError("invalid numeric text")
    result = Decimal(text)
    if not result.is_finite():
        raise ValueError("non-finite number")
    return result


def values_equal(expected: Any, actual: Any, *, path: str, product: str | None) -> bool:
    """数字字符串兼容只作用于声明字段；整数、Boolean 与身份类型不会被弱化。"""
    if expected is None or actual is None:
        return expected is actual
    kind = _field_kind(path, product)
    if kind in {"integer", "long"}:
        return type(expected) is int and type(actual) is int and expected == actual
    if kind in {"decimal", "numeric_text", "percentage"}:
        try:
            return _decimal(expected, percentage=kind == "percentage") == _decimal(actual, percentage=kind == "percentage")
        except (ValueError, InvalidOperation):
            return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    return bool(expected == actual)
