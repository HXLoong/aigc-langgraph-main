"""Java 入参的类型兼容清洗；不换算业务单位、不填默认交易值。"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# 此表只镜像接口字段类型，不维护证券、账户或其它业务数据映射。
OPTION_FIELDS = {
    **dict.fromkeys(("id", "quickInquiryOrderId"), "long"),
    **dict.fromkeys(("isValid", "snowballTenorMonths", "snowballLockInPeriodMonths"), "integer"),
    **dict.fromkeys(("notionalAmount", "limitPrice", "povRatio", "placeOrderPrice"), "decimal"),
    **dict.fromkeys(("premiumRatePct", "strikePercentage", "participationRate",
                    "snowballKnockOutUpperBarrierPct", "snowballKnockInLowerBarrierPct",
                    "snowballMarginPercentagePct", "snowballAnnualizedCouponRatePct",
                    "snowballAbsoluteCouponRatePct"), "percentage"),
    "orderId": "identity", "tenor": "tenor", "hasFastExecutionIntent": "boolean",
    "placeOrderQuantity": "long",
}
SWAP_FIELDS = {
    **dict.fromkeys(("placeOrderQuantity", "placeOrderQuantityHand", "placeOrderDisplayQty",
                    "placeOrderQuantityTotal"), "long"),
    **dict.fromkeys(("placeOrderNotional", "placeOrderPrice", "placeOrderPovPercent",
                    "placeOrderTotalPovPercent", "placeOrderMaxVol", "placeOrderEntrustRatio"), "decimal"),
    **dict.fromkeys(("placeOrderPremarket", "placeOrderCloseIntent", "hasFastExecutionIntent"), "boolean"),
    **dict.fromkeys(("placeOrderStartTime", "placeOrderEndTime"), "time"),
    "placeOrderRelativeTimeMinutes": "numeric_text", "orderId": "identity",
}
CLOSE_FIELDS = {
    **dict.fromkeys(("closeOrderPrice", "closeOrderPovRatio", "price"), "decimal"),
    **dict.fromkeys(("confirmFullClose", "hasFastExecutionIntent"), "boolean"),
    "closeOrderNotionalDelta": "numeric_text", "orderId": "identity",
    "internalTradeId": "identity", "contractCode": "identity", "qty": "long",
}
IDENTITY_LISTS = frozenset({
    "confirmOrderNoList", "cancelOrderNoList", "confirmCancelOrderNoList", "queryOrderNoList",
    "internalTradeIdList", "contractCodeList", "keyInstrumentIdList", "keyCtptyIdList",
})
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_TIME = re.compile(r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2} )?[0-9]{2}:[0-9]{2}(?::[0-9]{2})?\Z")
_OMIT = object()


@dataclass(frozen=True)
class CleanedRequest:
    """出站业务部分与诊断记录；原输入始终保持不变。"""

    payload: dict[str, Any]
    changes: list[dict[str, Any]]
    original: dict[str, Any]
    json_fallback: bool = False


def is_empty_parameter(value: Any) -> bool:
    """只识别完整空占位，不把 0、false 或文本中的 null 子串当空值。"""
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "null"})


def _number(value: Any) -> Decimal:
    """读取有限十进制值；先排除 bool，防止 Python 把它当作整数。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("not_numeric")
    text = str(value).strip()
    if not _NUMBER.fullmatch(text):
        raise ValueError("not_numeric")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("not_numeric") from exc
    if not number.is_finite():
        raise ValueError("not_finite")
    return number


def _scalar(value: Any, kind: str) -> Any:
    """按传输类型装配，无法无损表达时仅返回省略标记。"""
    # 身份字段不能通过空字符串清洗而改变用户选择；真正未提供的 None 可省略。
    if kind == "identity":
        if value is None:
            return _OMIT
        if not isinstance(value, str) or is_empty_parameter(value):
            raise ValueError("订单或合约身份不是有效字符串")
        return value
    if is_empty_parameter(value):
        return _OMIT
    try:
        if kind in {"integer", "long", "decimal", "numeric_text"}:
            number = _number(value)
            if kind in {"integer", "long"}:
                bits = 32 if kind == "integer" else 64
                if number != number.to_integral_value() or not -(2 ** (bits - 1)) <= number < 2 ** (bits - 1):
                    return _OMIT
                return int(number)
            if kind == "numeric_text":
                return str(number)
            if isinstance(value, (int, float, Decimal)):
                return value
            return number
        if kind == "percentage":
            # Java PercentageDeserializer 接受百分号后缀，原字符串交给它处理。
            if isinstance(value, str) and value.strip().endswith(("%", "％")):
                _number(value.strip()[:-1].strip())
                return value
            number = _number(value)
            return value if isinstance(value, (int, float, Decimal)) else number
        if kind == "boolean":
            return value if isinstance(value, bool) else _OMIT
        if kind == "time":
            if not isinstance(value, str) or not _TIME.fullmatch(value.strip()):
                return _OMIT
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
                try:
                    datetime.strptime(value.strip(), pattern)
                    return value
                except ValueError:
                    continue
            return _OMIT
        if kind == "tenor" and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return str(_number(value))
        return value if isinstance(value, str) else _OMIT
    except (ValueError, InvalidOperation, OverflowError):
        return _OMIT


def _audit_value(value: Any) -> Any:
    """诊断值可 JSON 序列化；原始模型输出另由解析与 Generation 保存。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _audit_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_audit_value(item) for item in value]
    if isinstance(value, float) and not Decimal(str(value)).is_finite():
        return str(value)
    return deepcopy(value)


def _clean_object(data: dict[str, Any], rules: dict[str, str], path: str,
                  changes: list[dict[str, Any]]) -> dict[str, Any]:
    """递归清洗业务对象，列表身份和订单下标保持稳定。"""
    result: dict[str, Any] = {}
    for key, value in data.items():
        field_path = f"{path}.{key}" if path else key
        kind = rules.get(key, "text")
        if isinstance(value, dict) and key == "contractQuery":
            result[key] = _clean_object(value, {"allowCloseOut": "boolean_text"}, field_path, changes)
            continue
        if isinstance(value, list) and key in IDENTITY_LISTS:
            # 指定范围整体校验；不能丢一个 ID 后扩大或改变查询/交易范围。
            item_kind = "integer" if key == "keyCtptyIdList" else "identity"
            items = [_scalar(item, item_kind) for item in value]
            if any(item is _OMIT for item in items):
                raise ValueError(f"身份列表包含无效元素：{field_path}")
            result[key] = items
            continue
        if isinstance(value, list) and key in {"closeOrderList", "orderList"}:
            result[key] = _clean_orders(value, rules, field_path, changes)
            continue
        if isinstance(value, list) and key.endswith("List"):
            # 普通过滤列表仅清空项；不推断原文中的证券、账户或枚举。
            items = [_scalar(item, "text") for item in value]
            result[key] = [item for item in items if item is not _OMIT]
            if len(result[key]) == len(value):
                continue
            cleaned: Any = result[key]
        elif key == "allowCloseOut" and isinstance(value, bool):
            cleaned = "true" if value else "false"
        else:
            cleaned = _scalar(value, kind)
        if cleaned is not _OMIT:
            result[key] = cleaned
        if cleaned is _OMIT or type(cleaned) is not type(value) or cleaned != value:
            changes.append({
                "path": field_path, "original_value": _audit_value(value), "expected_type": kind,
                "action": "omit" if cleaned is _OMIT else "convert",
                "reason": "empty" if is_empty_parameter(value) else "incompatible_type" if cleaned is _OMIT else "lossless_conversion",
                "submitted_value": None if cleaned is _OMIT else _audit_value(cleaned),
            })
    return result


def _clean_orders(orders: Any, rules: dict[str, str], path: str,
                  changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """一笔输入对应一笔输出，损坏的订单对象不能被删除后继续提交。"""
    if orders is None:
        return []
    if not isinstance(orders, list) or any(not isinstance(order, dict) for order in orders):
        raise ValueError(f"订单列表结构错误：{path}")
    return [_clean_object(order, rules, f"{path}.{index}", changes) for index, order in enumerate(orders)]


def clean_business_request(product: str, data: dict[str, Any] | str, *,
                           intent: str | None = None) -> CleanedRequest:
    """清洗三个普通业务入口；字符串 JSON 解码失败严格采用 Dify 空对象回退。"""
    # 1. 只捕获 JSON 解码失败；合法 JSON 的错误对象形状仍显式报错。
    fallback = False
    if isinstance(data, str):
        try:
            data = json.loads(data) if data.strip() else {}
            fallback = not bool(data) if isinstance(data, dict) else False
        except json.JSONDecodeError:
            data, fallback = {}, True
    if not isinstance(data, dict):
        raise ValueError("业务请求必须是 JSON 对象")
    data = deepcopy(data)
    changes: list[dict[str, Any]] = []
    # 2. 顶层动作不清洗、不猜测。平仓动作原本就位于参数对象之外。
    payload: dict[str, Any]
    if product == "close":
        payload = {"type": intent, "closeOrderReqVO": _clean_object(data, CLOSE_FIELDS, "closeOrderReqVO", changes),
                   "operate": "", "orderList": [], "optionRfq": {}}
    elif product in {"option", "swap"}:
        rules = OPTION_FIELDS if product == "option" else SWAP_FIELDS
        payload = {"type": data.get("type"), "orderList": _clean_orders(data.get("orderList", []), rules, "orderList", changes)}
        if product == "option":
            payload["operate"] = data.get("operate")
            if "optionRfq" in data:
                payload["optionRfq"] = data["optionRfq"]
    else:
        raise ValueError(f"未知清洗产品：{product}")
    if fallback:
        changes.insert(0, {"path": "$", "action": "json_fallback", "reason": "empty_or_invalid_json"})
    return CleanedRequest(payload, changes, data, fallback)
