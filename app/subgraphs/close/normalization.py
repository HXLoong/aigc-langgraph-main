"""Close candidates carry original text; Code owns identities, arithmetic and filters."""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_FLOOR, Decimal
from typing import Any, cast

from pydantic import BaseModel

from app.extraction.candidates import candidate_model, verify_candidates
from app.extraction.fields import EvidenceError, FieldCandidate, FieldRecord
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams, HoldingQueryParams
from app.subgraphs.close.order_id import CONTRACT_CODE_RE, ORDER_ID_RE, _ordinal_value
from app.subgraphs.close.reference_parser import ReferenceParseResult
from app.subgraphs.option.normalize import _cn_number

_SEQ = re.compile(r"序号\s*[:：]?\s*(\d+)|第\s*([零〇一二两三四五六七八九十百\d]+)\s*笔")
_FULL = re.compile(r"全部平仓|确认全部平仓|全平|全部平掉")
_KEEP = re.compile(r"(?:保留|只留|留|平到还剩|平到剩|平剩到|剩到|剩)\s*([\d零〇一二两三四五六七八九十百千.]+\s*(?:千万|百万|kw|KW|[万亿wWkKeE])?)")
_ENUMS = {
    "closeOrderType": {"市价单": ("市价", "市价单", "market", "mkt", "不用跟量", "不跟量", "不要跟量"),
                       "限价单": ("限价", "限价单", "limit", "lmt"),
                       "POV": ("pov", "跟量", "正常挂单", "最大跟量", "拉满跟量", "全跟量"),
                       "TWAP": ("twap", "时间加权", "时间均价", "均匀执行")},
    "insFamilyList": {"EQUITY": ("股票", "个股"), "INDEX": ("指数",),
                      "FUND": ("基金", "ETF"), "FUTURE": ("期货",)},
    "contractTypeList": {"EUROPEAN_VANILLA": ("欧式", "欧式期权", "欧式看涨", "香草"),
                         "AUTOCALL": ("雪球",), "PARTICIPATORY": ("参与型", "参与型看涨"),
                         "AIRBAG": ("气囊", "安全气囊")},
}


def _enum(alias: str, text: str) -> str:
    for value, words in _ENUMS[alias].items():
        if text.casefold() in {word.casefold() for word in (value, *words)}:
            return value
    raise ValueError(f"无法归一化平仓枚举 {alias}")


def _number(text: str) -> Decimal:
    token = re.sub(r"[,，\s]", "", text).removesuffix("元")
    match = re.fullmatch(r"([+-]?[\d零〇一二两三四五六七八九十百千.]+)(千万|百万|kw|KW|[万亿wWkKeE])?", token)
    if not match:
        raise ValueError("平仓金额或比例无法解析")
    raw = match[1]
    value = Decimal(raw) if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw) else Decimal(_cn_number(raw) or 0)
    scale = {"": 1, "万": 10000, "w": 10000, "k": 1000, "kw": 10000000,
             "千万": 10000000, "百万": 1000000, "亿": 100000000, "e": 100000000}
    return value * scale[(match[2] or "").lower()]


def _amount(value: str, row: Mapping[str, Any] | None) -> str | None:
    keep = _KEEP.search(value)
    token = re.sub(r"^(?:名义本金|名本|平掉|平仓|平|以|按)", "", value).strip()
    token = re.sub(r"(?:来平|平仓|平)$", "", token).strip()
    ratio: Decimal | None = None
    if "一半" in token:
        ratio = Decimal("0.5")
    elif token.endswith(("%", "％")):
        ratio = _number(token[:-1]) / 100
    elif token.endswith("成"):
        ratio = _number(token[:-1]) / 10
    elif "分之" in token or "/" in token:
        if "分之" in token:
            denominator, numerator = token.split("分之", 1)
        else:
            numerator, denominator = token.split("/", 1)
        top, bottom = _number(numerator), _number(denominator)
        if not 0 < top < bottom:
            return None
        ratio = top / bottom
    if keep or ratio is not None:
        available = (row or {}).get("availableNotional")
        if available is None:
            return None
        available = Decimal(str(available))
        if not available.is_finite() or available <= 0:
            return None
        if keep:
            remaining = _number(keep[1])
            amount = available - remaining if 0 < remaining < available else Decimal(0)
        else:
            if ratio is None or not 0 < ratio <= 1:
                return None
            amount = available * ratio
        return str(amount.to_integral_value(rounding=ROUND_FLOOR)) if amount >= 1 else None
    amount = _number(token)
    return format(amount, "f").rstrip("0").rstrip(".") if "." in format(amount, "f") else str(amount)


def _identity(selector: str, parsed: ReferenceParseResult, data: list[dict[str, Any]]) -> dict[str, Any]:
    oid = ORDER_ID_RE.fullmatch(selector)
    contract = CONTRACT_CODE_RE.fullmatch(selector)
    target: dict[str, Any] = {}
    if oid:
        target = {"orderId": oid[0]}
    elif contract:
        target = {"internalTradeId": contract[0]}
    elif match := _SEQ.fullmatch(selector):
        ordinal = _ordinal_value(match[1] or match[2]) or 0
        holdings = parsed["holdingMap"]
        # 序号 is a displayed label; 第 X 笔 is an ordinal position in the quote.
        quoted = next((h for h in holdings if h["seq"] == ordinal), None) if match[1] else (
            holdings[ordinal - 1] if 0 < ordinal <= len(holdings) else None)
        if quoted is not None:
            target = {"orderId": quoted.get("orderId"), "internalTradeId": quoted.get("contractId")}
        elif not holdings and 0 < ordinal <= len(data):
            selected = data[ordinal - 1]
            target = {"orderId": selected.get("orderId"), "internalTradeId": selected.get("contractCode")}
    if not any(target.values()):
        return {}
    matches = [item for item in data if (
        target.get("orderId") and item.get("orderId") == target["orderId"]
    ) or (target.get("internalTradeId") and item.get("contractCode") == target["internalTradeId"])]
    if len(matches) > 1:
        raise EvidenceError("平仓目标对应多条查询记录")
    if matches:
        record = matches[0]
        target = {"orderId": target.get("orderId") or record.get("orderId"),
                  "internalTradeId": target.get("internalTradeId") or record.get("contractCode")}
    return target


def _selectors(raw: str) -> list[str]:
    tokens = [(m.start(), m[0]) for pattern in (ORDER_ID_RE, CONTRACT_CODE_RE, _SEQ)
              for m in pattern.finditer(raw)]
    return list(dict.fromkeys(token for _, token in sorted(tokens)))


def _target_segments(
    raw: str, parsed: ReferenceParseResult, data: list[dict[str, Any]], target: dict[str, Any],
) -> list[str]:
    positions = sorted((m.start(), m[0]) for pattern in (ORDER_ID_RE, CONTRACT_CODE_RE, _SEQ)
                       for m in pattern.finditer(raw))
    segments = []
    for index, (start, token) in enumerate(positions):
        resolved = _identity(token, parsed, data)
        if resolved and all(not value or target.get(key) == value for key, value in resolved.items()):
            end = positions[index + 1][0] if index + 1 < len(positions) else len(raw)
            segments.append(raw[start:end])
    # Explicit shared qualifiers apply to the selected targets, never to unrelated holdings.
    segments.extend(m[0] for m in re.finditer(r"(?:^|[，,；;])\s*(?:全部|统一|都|均)[^，,；;]*", raw))
    return segments


def _record(value: Any, candidate: FieldCandidate | None = None, *, evidence: str = "", origin: str = "raw") -> FieldRecord:
    return FieldRecord(value=value, source="user", evidence=candidate.evidence if candidate else evidence,
                       origin=candidate.origin if candidate else origin,
                       confidence=candidate.confidence if candidate else None, locked=True)


def normalize_place_candidates(
    candidates: BaseModel, sources: Mapping[str, str], parsed: ReferenceParseResult,
    data: list[dict[str, Any]],
) -> tuple[ClosePlaceParams, dict[str, FieldRecord]]:
    candidates = candidate_model(ClosePlaceParams).model_validate(candidates.model_dump(by_alias=True))
    verify_candidates(candidates, sources)
    raw = sources.get("raw", "")
    explicit = _selectors(raw)
    selected = [_identity(token, parsed, data) for token in explicit]
    rows: list[dict[str, Any]] = []
    ledgers: list[dict[str, FieldRecord]] = []
    negated_full = bool(re.search(r"(?:不|别|不要|不想)\s*(?:全部平仓|全平|全部平掉)", raw))
    unbound_full = bool(re.search(r"(?:^|[，,；;])\s*(?:确认)?全部平仓[。！!\s]*$", raw)) or (
        bool(_FULL.search(raw)) and not explicit and not _KEEP.search(raw) and not negated_full
    )
    if cast(Any, candidates).close_order_list and not explicit and not unbound_full and len(parsed["pureErrorOrderIds"]) > 1:
        # Original contract: ambiguous supplements preserve identities, never broadcast a value.
        rows = [{"orderId": oid} for oid in parsed["pureErrorOrderIds"]]
        ledgers = [{} for _ in rows]
    else:
        for item in cast(Any, candidates).close_order_list:
            values = {info.alias or name: getattr(item, name) for name, info in type(item).model_fields.items()}
            identities = [c for key, c in values.items() if key in {"orderId", "internalTradeId"} and c and c.value]
            target: dict[str, Any] = {}
            for candidate in identities:
                proposed = _identity(candidate.value, parsed, data)
                if target and proposed and any(target.get(k) and target[k] != v for k, v in proposed.items() if v):
                    raise EvidenceError("平仓订单和合约身份冲突")
                target.update({k: v for k, v in proposed.items() if v})
            if explicit:
                if not target and len(selected) == 1:
                    target = selected[0]
                if target and not any(t and all(not v or t.get(k) == v for k, v in target.items()) for t in selected):
                    raise EvidenceError("模型候选超出本轮指定平仓范围")
            else:
                fallback = parsed["pureErrorOrderIds"] or [
                    str(h.get("orderId") or h.get("contractId")) for h in parsed["holdingMap"]
                    if h.get("orderId") or h.get("contractId")]
                if unbound_full:
                    fallback = parsed["fullCloseIds"]
                if unbound_full and target.get("orderId") not in fallback:
                    target = {}
                if len(fallback) == 1:
                    target = _identity(fallback[0], parsed, data)
                elif not unbound_full:
                    target = {}
            if not target:
                continue
            matching = next((d for d in data if (target.get("orderId") and d.get("orderId") == target["orderId"])
                             or (target.get("internalTradeId") and d.get("contractCode") == target["internalTradeId"])), None)
            row, ledger = dict(target), {}
            segments = _target_segments(raw, parsed, data, target) if explicit else [raw]
            for alias, candidate in values.items():
                if alias in {"orderId", "internalTradeId"} or candidate is None or candidate.value is None:
                    continue
                if candidate.origin != "raw":
                    raise EvidenceError("平仓执行参数必须来自本轮原文")
                text = candidate.value.strip()
                if not any(text in segment for segment in segments):
                    raise EvidenceError("平仓参数证据属于另一笔订单")
                value: Any = text
                if alias == "closeOrderNotionalDelta":
                    value = _amount(text, matching)
                elif alias == "closeOrderType":
                    value = _enum(alias, text)
                elif alias == "closeOrderPrice":
                    value = float(_number(text))
                elif alias == "closeOrderPovRatio":
                    number = _number(text.rstrip("%％"))
                    if number != number.to_integral_value():
                        raise ValueError("期权平仓跟量比例必须为整数百分比")
                    value = int(number)
                elif alias in {"closeOrderAlgoStartTime", "closeOrderAlgoEndTime"}:
                    match = re.fullmatch(r"(\d{1,2})[:：](\d{1,2})", text)
                    if not match or int(match[1]) > 23 or int(match[2]) > 59:
                        raise ValueError("TWAP 时间必须为有效 HH:MM")
                    value = f"{int(match[1]):02d}:{int(match[2]):02d}"
                elif alias == "confirmFullClose":
                    value = (bool(_FULL.search(text)) or text == "全部") and not bool(_KEEP.search(candidate.evidence))
                    if re.search(r"不|别|不要", candidate.evidence) or any(
                        re.search(r"(?:不|别|不要|不想)\s*(?:全部|全平)", segment) for segment in segments
                    ):
                        value = False
                row[alias], ledger[alias] = value, _record(value, candidate)
            amount_candidate = values.get("closeOrderNotionalDelta")
            if amount_candidate and amount_candidate.value and _KEEP.search(amount_candidate.value):
                row["confirmFullClose"] = None
                ledger.pop("confirmFullClose", None)
            type_candidate = values.get("closeOrderType")
            if type_candidate and type_candidate.value and any(
                word in type_candidate.value for word in ("最大跟量", "拉满跟量", "全跟量")
            ) and row.get("closeOrderPovRatio") is None and not row.get("confirmFullClose"):
                row["closeOrderPovRatio"] = 25
                ledger["closeOrderPovRatio"] = FieldRecord(
                    value=25, source="default", evidence=type_candidate.evidence, locked=True,
                )
            if row.get("closeOrderType") is None:
                inferred = "TWAP" if row.get("closeOrderAlgoStartTime") or row.get("closeOrderAlgoEndTime") else (
                    "POV" if row.get("closeOrderPovRatio") is not None else (
                        "限价单" if row.get("closeOrderPrice") is not None else None))
                if inferred:
                    row["closeOrderType"] = inferred
                    ledger["closeOrderType"] = FieldRecord(value=inferred, source="inferred", evidence=raw, locked=True)
            # A declined full-close instruction alone must not become a new write request.
            if row.get("confirmFullClose") is False and not any(
                row.get(key) is not None for key in values if key not in {"orderId", "internalTradeId", "confirmFullClose"}
            ):
                continue
            rows.append(row)
            ledgers.append(ledger)
    if unbound_full:
        for oid in parsed["fullCloseIds"]:
            index = next((i for i, row in enumerate(rows) if row.get("orderId") == oid), None)
            if index is None:
                rows.append({"orderId": oid})
                ledgers.append({})
                index = len(rows) - 1
            rows[index]["confirmFullClose"] = True
            ledgers[index]["confirmFullClose"] = _record(True, evidence=raw)
    # Successful quoted requests remain untouched unless this turn explicitly supplements them.
    if rows and parsed["messageType"] == "close_result":
        for row in parsed["successOrders"]:
            if row.get("orderId") not in {item.get("orderId") for item in rows}:
                rows.append(row)
                ledgers.append({})
    records: dict[str, FieldRecord] = {}
    canonical = ClosePlaceParams(closeOrderList=[CloseOrderItem.model_validate(row) for row in rows])
    for index, (canonical_row, ledger) in enumerate(zip(canonical.close_order_list, ledgers, strict=True)):
        for alias, value in canonical_row.model_dump().items():
            if value is not None:
                records[f"close/place_close.orderList.{index}.{alias}"] = ledger.get(alias) or _record(
                    value, evidence=";".join(explicit) or str(value), origin="quote" if not explicit else "raw")
    return canonical, records


def normalize_holding_candidates(
    candidates: BaseModel, sources: Mapping[str, str], counterparties: list[dict[str, Any]],
) -> tuple[HoldingQueryParams, dict[str, FieldRecord]]:
    candidates = candidate_model(HoldingQueryParams).model_validate(candidates.model_dump(by_alias=True))
    verify_candidates(candidates, sources)
    raw = sources.get("raw", "")
    values: dict[str, Any] = {"closeable_only": False}
    records: dict[str, FieldRecord] = {}
    for name, info in type(candidates).model_fields.items():
        alias = info.alias or name
        candidate_value = getattr(candidates, name)
        items = candidate_value if isinstance(candidate_value, list) else [candidate_value]
        output: list[Any] = []
        for candidate in items:
            if candidate is None or candidate.value is None:
                continue
            if candidate.origin != "raw":
                raise EvidenceError("持仓查询过滤条件必须来自本轮原文")
            text = candidate.value.strip()
            value: Any = text
            if alias == "closeable_only":
                value = bool(re.search(r"平仓|平掉|想平|要平|能平|可平|减仓|了结|止盈|止损", text))
                if re.search(r"不平|不想平|不要平|不减仓|不止", candidate.evidence):
                    value = False
            elif alias == "keyCtptyIdList":
                if not re.search(r"对手|交易对手|客户|账户", raw):
                    continue
                # Names are supplied by Java; unique literal containment permits common short names.
                matches = {c["ctptyId"] for c in counterparties if c.get("ctptyId") is not None and any(
                    text == str(c.get(key) or "") or text in str(c.get(key) or "")
                    for key in ("shortName", "longName"))}
                if len(matches) > 1:
                    raise ValueError("交易对手名称不唯一，请补充完整名称")
                value = next(iter(matches)) if matches else 99999999
            elif alias in _ENUMS:
                value = _enum(alias, text)
            elif alias == "internalTradeIdList" and not CONTRACT_CODE_RE.fullmatch(text):
                raise EvidenceError("合约编号格式不正确")
            output.append(value)
            suffix = f".{len(output) - 1}" if isinstance(candidate_value, list) else ""
            records[f"close/holding_query.{alias}{suffix}"] = _record(value, candidate)
        if isinstance(candidate_value, list):
            values[alias] = output
        elif output:
            values[alias] = output[0]
    return HoldingQueryParams.model_validate(values), records
