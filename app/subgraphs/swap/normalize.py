"""Deterministic swap field rules; instrument/account data remain backend-owned."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from app.extraction.candidates import unpack_candidates
from app.extraction.fast_execution import resolve_fast_execution
from app.extraction.fields import FieldCandidate, FieldRecord
from app.subgraphs.option.normalize import _cn_number
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams

_SCALES = {"": 1, "k": 1000, "千": 1000, "w": 10000, "万": 10000,
           "百万": 1000000, "千万": 10000000, "亿": 100000000}
_CURRENCIES = {
    "CNY": ("人民币", "人民币元", "元", "块", "￥", "¥", "RMB", "CNY"),
    "USD": ("美元", "美金", "USD"), "HKD": ("港元", "港币", "HKD"),
    "EUR": ("欧元", "EUR"), "GBP": ("英镑", "GBP"), "JPY": ("日元", "JPY"),
    "AUD": ("澳元", "AUD"), "NZD": ("纽元", "NZD"), "CNH": ("离岸人民币", "CNH"),
}
_ENUMS: dict[str, dict[str, tuple[str, ...]]] = {
    "placeOrderOrderDirection": {
        "BUY": ("买入", "買入", "买", "買", "做多", "多头开仓", "BUY"),
        "SELL": ("卖出", "賣出", "卖", "賣", "平多", "卖出平仓", "SELL"),
        "SHORT_OPEN": ("卖空", "賣空", "做空", "空头开仓", "SHORT_OPEN"),
        "SHORT_CLOSE": ("平空", "买入平仓", "買入平倉", "SHORT_CLOSE"),
    },
    "placeOrderPriceType": {
        "MarketOrder": ("市价", "市價", "不限价", "不限價", "MKT", "MARKET", "MarketOrder"),
        "LimitOrder": ("限价", "限價", "限价委托", "限價委託", "LMT", "LIMIT", "LimitOrder"),
    },
    "placeOrderAlgorithmType": {
        "POV": ("POV", "跟量", "占比"), "TWAP": ("TWAP", "全天均价", "全天均價", "时间均价", "均价"),
        "VWAP": ("VWAP", "成交量均价"), "ICEBERG": ("ICEBERG", "冰山"), "SNIPER": ("SNIPER", "狙击"),
    },
    "placeOrderTransactionType": {
        "A_SHARE": ("A股", "A_SHARE"), "HK_STOCK": ("港股", "HK_STOCK"),
        "US_STOCK": ("美股", "US_STOCK"), "SZ_HK_CONNECT": ("深港通", "SZ_HK_CONNECT"),
        "SH_HK_CONNECT": ("沪港通", "滬港通", "SH_HK_CONNECT"),
        "CHN_FUTURE": ("境内期货", "境內期貨", "CHN_FUTURE"),
        "CROSS_FUTURE": ("跨境期货", "跨境期貨", "CROSS_FUTURE"),
    },
}
_QUANTITIES = {"placeOrderQuantity", "placeOrderQuantityHand", "placeOrderQuantityTotal", "placeOrderDisplayQty"}
_NUMBERS = {"placeOrderPrice", "placeOrderNotional", "placeOrderMaxVol"}
_PERCENTAGES = {"placeOrderPovPercent", "placeOrderTotalPovPercent"}
_TIMES = {"placeOrderStartTime", "placeOrderEndTime"}
_BOOLEAN_FIELDS = {"placeOrderCloseIntent", "placeOrderPremarket"}
_DIRECTION_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:BUY|SELL|SHORT_OPEN|SHORT_CLOSE|[BSL])(?![A-Za-z0-9_.-])"
    r"|买入|卖出|買入|賣出|平空|平多|做多|做空|卖空|买|卖", re.I,
)


def _direction_shorthand(value: str, context: str) -> str:
    markers = [marker for marker in _DIRECTION_TOKEN.finditer(context) if not re.search(
        r"(?:交易对手|对手|账号|账户|簿记|选择|选)\s*[:：]?\s*$", context[:marker.start()],
    )]
    if not markers or markers[0][0].upper() != value.upper():
        raise ValueError("方向缩写必须是该笔订单第一个独立方向标记")
    return "SELL" if value.upper() == "S" else "BUY"


def _direction_context(candidate: FieldCandidate, sources: Mapping[str, str]) -> str:
    key = candidate.origin if candidate.reference is None else f"{candidate.origin}:{candidate.reference}"
    source = sources.get(key, "")
    # A one-letter evidence must not conceal its actual account/ticker context.
    contexts = [part for part in re.split(r"[\n；;]", source) if candidate.evidence in part]
    if len(contexts) != 1:
        raise ValueError("方向缩写无法唯一归属当前订单，请提供完整方向")
    return contexts[0]


def _number(text: str) -> Decimal:
    value = re.sub(r"[,，\s]", "", text).strip()
    suffixes = [alias for aliases in _CURRENCIES.values() for alias in aliases]
    suffixes += ["标准手", "标准股", "标手", "整手", "单合约", "LOTS", "LOT", "股", "手", "张", "%"]
    for suffix in sorted(suffixes, key=len, reverse=True):
        if value.upper().endswith(suffix.upper()):
            value = value[:-len(suffix)]
            break
    value = value.lstrip("￥¥")
    match = re.fullmatch(r"([+-]?[0-9]+(?:\.[0-9]+)?)(千万|百万|亿|万|千|[kKwW])?", value)
    if match:
        number = Decimal(match[1]) * _SCALES[(match[2] or "").lower()]
    else:
        chinese = re.fullmatch(r"([零〇一二两三四五六七八九十百千]+)(万|亿)?", value)
        if not chinese:
            raise ValueError("无法解析数值")
        amount = _cn_number(chinese[1])
        if amount is None:
            raise ValueError("无法解析中文数值")
        number = Decimal(amount) * _SCALES[chinese[2] or ""]
    if not number.is_finite():
        raise ValueError("数值必须有限")
    return number


def quantity_unit(text: str) -> str | None:
    if re.search(r"(?:标准手|标手|整手|手|单合约|张|lots?)$", text.strip(), re.IGNORECASE):
        return "HAND"
    if text.strip().endswith("股"):
        return "SHARE"
    if currency(text) or re.search(r"(?:千万|百万|亿|万|千|[kKwW])$", text.strip()):
        return "AMOUNT"
    return None


def currency(text: str) -> str | None:
    candidates = sorted(((alias, code) for code, aliases in _CURRENCIES.items() for alias in aliases),
                        key=lambda pair: len(pair[0]), reverse=True)
    for alias, code in candidates:
        if text.upper().endswith(alias.upper()) or (alias in {"￥", "¥"} and text.startswith(alias)):
            return code
    return None


def close_ratio(value: str, evidence: str) -> float | None:
    if not any(word in evidence for word in ("平", "清仓", "清倉", "全卖", "全賣", "半仓", "一半")):
        return None
    if any(word in value for word in ("全部", "全平", "全数", "全賣", "全卖", "清仓", "清倉")):
        result = Decimal(1)
    elif "一半" in value or "半仓" in value:
        result = Decimal("0.5")
    else:
        token = re.sub(r"^(?:平掉|平仓|平倉|平|以)", "", value).strip()
        if token.endswith("%"):
            result = _number(token) / 100
        elif token.endswith("成"):
            result = _number(token[:-1]) / 10
        elif "分之" in token:
            denominator, numerator = token.split("分之", 1)
            result = _number(numerator) / _number(denominator)
        elif "/" in token:
            numerator, denominator = token.split("/", 1)
            result = _number(numerator) / _number(denominator)
        else:
            result = _number(token)
    if not 0 < result <= 1:
        raise ValueError("平仓比例必须在 (0, 100%] 范围内")
    return float(result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def normalize_field(field: str, value: str, evidence: str | None = None) -> Any:
    """Values are verified raw fragments; this function performs no security-data lookup."""
    text = value.strip()
    evidence = evidence or text
    if field == "placeOrderOrderDirection" and text.upper() in {"B", "S", "L"}:
        return _direction_shorthand(text, evidence)
    if field in _ENUMS:
        for normalized, aliases in _ENUMS[field].items():
            if any(text.upper() == alias.upper() for alias in aliases):
                return normalized
        raise ValueError(f"无法识别枚举字段 {field}")
    if field == "placeOrderQuantityUnit":
        return text.upper() if text.upper() in {"HAND", "SHARE", "AMOUNT"} else quantity_unit(text)
    if field == "placeOrderNotionalCurrency":
        return currency(text)
    if field == "placeOrderEntrustRatio":
        try:
            return close_ratio(text, evidence)
        except (InvalidOperation, ZeroDivisionError) as exc:
            raise ValueError("平仓比例无法解析") from exc
    if field in _QUANTITIES | _NUMBERS | _PERCENTAGES:
        number = _number(text)
        if number <= 0:
            raise ValueError(f"{field} 必须大于零")
        if field in _QUANTITIES and number != number.to_integral_value():
            raise ValueError("委托数量展开后必须是整数")
        if field in _PERCENTAGES and number > 100:
            raise ValueError("跟量比例不能超过 100%")
        return int(number) if number == number.to_integral_value() else float(number)
    if field in _TIMES:
        match = re.fullmatch(r"([0-9]{1,2})[:：]([0-9]{1,2})", text)
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError("时间必须为有效 HH:MM")
        return f"{int(match[1]):02d}:{int(match[2]):02d}"
    if field == "placeOrderRelativeTimeMinutes":
        if text in {"半小时", "半小時"}:
            return 30
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(分钟|分鐘|小时|小時|分钟内|分鐘內)", text)
        if not match:
            raise ValueError("相对时间缺少有效数字与单位")
        return float(match[1]) * (60 if match[2] in {"小时", "小時"} else 1)
    if field == "hasFastExecutionIntent":
        return resolve_fast_execution(evidence or text)
    if field in _BOOLEAN_FIELDS:
        if text.lower() in {"false", "否", "不"} or re.search(r"不要|无需|不需要|不平|非盘前", evidence):
            return False
        signals = {
            "placeOrderPremarket": ("盘前", "盤前", "集合竞价", "集合競價"),
            "placeOrderCloseIntent": ("平仓", "平倉", "清仓", "清倉", "平空", "平多", "平掉", "全平", "减仓"),
        }
        if text.lower() in {"true", "是"} or any(signal in text for signal in signals[field]):
            return True
        raise ValueError(f"{field} 缺少明确语义")
    return value


def normalize_candidates(
    candidates: BaseModel, sources: Mapping[str, str], *, scope: str = "swap/place_order",
) -> tuple[SwapPlaceOrderParams, dict[str, FieldRecord]]:
    def converter(alias: str) -> Callable[[str, FieldCandidate], Any]:
        def convert(value: str, candidate: FieldCandidate) -> Any:
            if alias == "hasFastExecutionIntent" and candidate.origin not in {"raw", "attachment"}:
                return None  # 引用和历史不构成本轮最大跟量意图。
            if alias == "placeOrderQuantity" and quantity_unit(value) == "AMOUNT":
                return None  # the linked notional field is derived below from the same evidence
            context = candidate.evidence
            if alias == "placeOrderOrderDirection" and value.upper() in {"B", "S", "L"}:
                context = _direction_context(candidate, sources)
            return normalize_field(alias, value, context)
        return convert

    converters = {info.alias or name: converter(info.alias or name) for name, info in SwapOrderItem.model_fields.items()}
    raw_orders = candidates.model_dump(by_alias=True).get("orderList") or []
    split_units: dict[int, tuple[str, FieldCandidate, FieldCandidate]] = {}
    for index, raw_order in enumerate(raw_orders):
        raw_quantity, raw_unit = raw_order.get("placeOrderQuantity"), raw_order.get("placeOrderQuantityUnit")
        if not raw_quantity or not raw_unit:
            continue
        quantity_candidate, unit_candidate = FieldCandidate.model_validate(raw_quantity), FieldCandidate.model_validate(raw_unit)
        quantity_value, unit_value = quantity_candidate.verify(sources), unit_candidate.verify(sources)
        if (quantity_value is None or unit_value is None
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", quantity_value)
                or unit_value.upper() in {"SHARE", "HAND", "AMOUNT"}):
            continue
        token = quantity_value + unit_value
        if quantity_unit(token) is None:
            raise ValueError("无法确定数量单位")
        split_units[index] = (token, quantity_candidate, unit_candidate)

        def scaled_quantity(value: str, candidate: FieldCandidate, *, token: str = token) -> Any:
            return None if quantity_unit(token) == "AMOUNT" else normalize_field("placeOrderQuantity", token)

        converters[f"{scope}.orderList.{index}.placeOrderQuantity"] = scaled_quantity
    params, records = unpack_candidates(SwapPlaceOrderParams, candidates, sources, scope=scope,
                                        normalizers=converters)
    orders = []
    for index, item in enumerate(params.order_list):
        row = item.model_dump()
        original = raw_orders[index]
        prefix = f"{scope}.orderList.{index}."
        fast = original.get("hasFastExecutionIntent")
        if fast and fast.get("value") is not None and row.get("hasFastExecutionIntent") is not None:
            candidate = FieldCandidate.model_validate(fast)
            context = candidate.evidence
            # 单笔可核对完整原文中的否定；多笔只用本笔证据，不能全局扫描最大跟量。
            if candidate.origin == "raw" and len(raw_orders) == 1:
                context = sources.get("raw", context)
            elif candidate.origin == "attachment" and candidate.reference:
                reference = candidate.reference.split(":column:", 1)[0]
                if ":row:" in reference or len(raw_orders) == 1:
                    context = sources.get(f"attachment:{reference}", context)
            row["hasFastExecutionIntent"] = resolve_fast_execution(
                context, has_explicit_pov_ratio=any(row.get(field) is not None for field in _PERCENTAGES),
            )
        if index in split_units:
            _, quantity_candidate, unit_candidate = split_units[index]
            dependencies = []
            for field, candidate in (("placeOrderQuantity", quantity_candidate), ("placeOrderQuantityUnit", unit_candidate)):
                path = prefix + field + ".candidate"
                records[path] = records[prefix + field].model_copy(update={"value": candidate.value})
                dependencies.append(path)
            records[prefix + "placeOrderQuantity"] = records[prefix + "placeOrderQuantity"].model_copy(
                update={"source": "inferred", "derived_from": dependencies,
                        "confidence": min(quantity_candidate.confidence, unit_candidate.confidence)},
            )
        if row.get("placeOrderPrice") is not None and row.get("placeOrderPriceType") is None:
            row["placeOrderPriceType"] = "LimitOrder"
            records[prefix + "placeOrderPriceType"] = records[prefix + "placeOrderPrice"].model_copy(
                update={"value": "LimitOrder", "source": "inferred"},
            )
        for source_field in ("placeOrderQuantity", "placeOrderNotional"):
            raw_field = original.get(source_field)
            if not raw_field or raw_field.get("value") is None:
                continue
            raw = raw_field["value"]
            if source_field == "placeOrderQuantity" and index in split_units:
                raw = split_units[index][0]
            evidence = raw_field.get("evidence") or raw
            source_record = records[prefix + source_field]
            unit = quantity_unit(raw)
            # Quantity@price has an explicit quantity role even without 股/手.
            at_price = (source_field == "placeOrderQuantity" and currency(raw) is None
                        and not original.get("placeOrderQuantityUnit") and re.search(
                re.escape(raw) + r"\s*@\s*(?:[0-9]|mkt|market|市价)",
                sources.get(source_record.origin, ""), re.IGNORECASE,
            ))
            if at_price:
                unit = "SHARE" if re.search(r"[kKwW千万亿]", raw) else None
                row["placeOrderQuantity"] = normalize_field("placeOrderQuantity", raw, evidence)
            if unit and row.get("placeOrderQuantityUnit") not in {None, unit}:
                raise ValueError("数值中的单位与显式数量单位冲突")
            if unit and row.get("placeOrderQuantityUnit") is None:
                row["placeOrderQuantityUnit"] = unit
                records[prefix + "placeOrderQuantityUnit"] = source_record.model_copy(
                    update={"value": unit, "source": "inferred"},
                )
            if unit == "AMOUNT" and not at_price:
                row["placeOrderNotional"] = normalize_field("placeOrderNotional", raw, evidence)
                if source_field == "placeOrderQuantity":
                    row["placeOrderQuantity"] = None
                records[prefix + "placeOrderNotional"] = source_record.model_copy(
                    update={"value": row["placeOrderNotional"], "source": "inferred"},
                )
                denomination = currency(raw)
                if denomination and row.get("placeOrderNotionalCurrency") is None:
                    row["placeOrderNotionalCurrency"] = denomination
                    records[prefix + "placeOrderNotionalCurrency"] = source_record.model_copy(
                        update={"value": denomination, "source": "inferred"},
                    )
        for alias, value in row.items():
            path = prefix + alias
            if path in records:
                records[path] = records[path].model_copy(update={
                    "value": value, "locked": alias not in {"placeOrderWindCode", "placeOrderShortname"},
                })
        orders.append(row)
    return SwapPlaceOrderParams.model_validate({"orderList": orders}), records
