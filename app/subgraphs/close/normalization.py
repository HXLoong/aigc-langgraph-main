"""Close candidates carry original text; Code owns identities, arithmetic and filters."""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_FLOOR, Decimal
from typing import Any, cast

from pydantic import BaseModel

from app.extraction.candidates import candidate_model, verify_candidates
from app.extraction.fast_execution import resolve_fast_execution
from app.extraction.fields import EvidenceError, FieldCandidate, FieldRecord
from app.subgraphs.close.models import (
    CloseOrderItem,
    ClosePlaceParams,
    ClosePriceType,
    HoldingQueryParams,
)
from app.subgraphs.close.order_id import CONTRACT_CODE_RE, ORDER_ID_RE, _ordinal_value
from app.subgraphs.close.order_type import (
    is_fast_execution_phrase,
    normalize_close_order_type,
)
from app.subgraphs.close.reference_parser import ReferenceParseResult
from app.subgraphs.option.normalize import _cn_number

_SEQ = re.compile(r"序号\s*[:：]?\s*(\d+)|第\s*([零〇一二两三四五六七八九十百\d]+)\s*笔")
_FULL = re.compile(r"全部平仓|确认全部平仓|全平|全部平掉")
_NEGATED_FULL = re.compile(r"(?:不|别|不要|不想|不用|无需)\s*(?:全部|全平)")
_KEEP = re.compile(r"(?:保留|只留|留|平到还剩|平到剩|平剩到|剩到|剩)\s*([\d零〇一二两三四五六七八九十百千.]+\s*(?:千万|百万|kw|KW|[万亿wWkKeE])?)")
_ENUMS = {
    "insFamilyList": {"EQUITY": ("股票", "个股"), "INDEX": ("指数",),
                      "FUND": ("基金", "ETF"), "FUTURE": ("期货",)},
    "contractTypeList": {"EUROPEAN_VANILLA": ("欧式", "欧式期权", "欧式看涨", "香草"),
                         "AUTOCALL": ("雪球",), "PARTICIPATORY": ("参与型", "参与型看涨"),
                         "AIRBAG": ("气囊", "安全气囊")},
}


class CloseAmountError(ValueError):
    """用户给出的平仓金额不合法（0 / 负数），直接提示用户修改。"""


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
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        value = Decimal(raw)
    else:
        # 中文数字解析失败必须报错，不能编造成 0 发给 Java
        cn_value = _cn_number(raw)
        if cn_value is None:
            raise ValueError("平仓金额或比例无法解析")
        value = Decimal(cn_value)
    scale = {"": 1, "万": 10000, "w": 10000, "k": 1000, "kw": 10000000,
             "千万": 10000000, "百万": 1000000, "亿": 100000000, "e": 100000000}
    return value * scale[(match[2] or "").lower()]


def _amount(value: str, row: Mapping[str, Any] | None) -> str | None:
    keep = _KEEP.search(value)
    # 前缀可叠加：「平仓名义本金200万」「按名义本金100万平」
    token = re.sub(r"^(?:(?:名义本金|名本|平掉|平仓|平|以|按)\s*)+", "", value).strip()
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
    if amount <= 0:
        # 业务裁决 C8：0 / 负数本地拦截；超额等其余金额策略仍交给 Java
        raise CloseAmountError("平仓名义本金必须大于0，请修改后重新提交。")
    return format(amount, "f").rstrip("0").rstrip(".") if "." in format(amount, "f") else str(amount)


def _matching_record(
    target: Mapping[str, Any], data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """订单记录按订单号匹配；纯合约查询优先使用未绑定订单的持仓记录。"""
    if target.get("orderId"):
        matches = [row for row in data if row.get("orderId") == target["orderId"]]
    elif target.get("internalTradeId"):
        matches = [row for row in data if row.get("contractCode") == target["internalTradeId"]]
        unbound = [row for row in matches if not row.get("orderId")]
        matches = unbound or matches
    else:
        return None
    if len(matches) > 1:
        raise EvidenceError("平仓目标对应多条查询记录")
    if not matches:
        return None
    record = matches[0]
    if (target.get("internalTradeId") and record.get("contractCode")
            and target["internalTradeId"] != record["contractCode"]):
        raise EvidenceError("平仓订单和合约身份冲突")
    return record


def _identity(selector: str, parsed: ReferenceParseResult, data: list[dict[str, Any]]) -> dict[str, Any]:
    oid = ORDER_ID_RE.fullmatch(selector)
    contract = CONTRACT_CODE_RE.fullmatch(selector)
    target: dict[str, Any] = {}
    if oid:
        target = {"orderId": oid[0]}
    elif contract:
        target = {"internalTradeId": contract[0]}
        quoted_orders = {row["orderId"] for row in parsed["holdingMap"]
                         if row.get("contractId") == contract[0] and row.get("orderId")}
        if len(quoted_orders) > 1:
            raise EvidenceError("合约对应多笔引用订单，请明确订单号或序号")
        if quoted_orders:
            target["orderId"] = quoted_orders.pop()
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
    record = _matching_record(target, data)
    if record is not None:
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
            # The prefix before the first target belongs to that target, including
            # negation such as “不要对 CO-... 市价下单”; do not copy it to later orders.
            segments.append(raw[0 if index == 0 else start:end])
    # Explicit shared qualifiers apply to the selected targets, never to unrelated holdings.
    segments.extend(m[0] for m in re.finditer(r"(?:^|[，,；;])\s*(?:全部|统一|都|均)[^，,；;]*", raw))
    return segments


def _record(value: Any, candidate: FieldCandidate | None = None, *, evidence: str = "", origin: str = "raw") -> FieldRecord:
    return FieldRecord(value=value, source="user", evidence=candidate.evidence if candidate else evidence,
                       origin=candidate.origin if candidate else origin,
                       confidence=candidate.confidence if candidate else None, locked=True)


def _inferred_order_type(row: Mapping[str, Any]) -> ClosePriceType | None:
    if row.get("closeOrderAlgoStartTime") or row.get("closeOrderAlgoEndTime"):
        return "TWAP"
    if row.get("closeOrderPovRatio") is not None:
        return "POV"
    return "限价单" if row.get("closeOrderPrice") is not None else None


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
    # 业务裁决 C5：点名了具体订单时「全部平仓」只作用于被点名的订单，不再扩展到引用里其它只能全平的订单
    unbound_full = not explicit and (
        bool(re.search(r"(?:^|[，,；;])\s*(?:确认)?全部平仓[。！!\s]*$", raw))
        or (bool(_FULL.search(raw)) and not _KEEP.search(raw) and not negated_full)
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
            matching = _matching_record(target, data)
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
                elif alias == "closeOrderPrice":
                    value = float(_number(text))
                elif alias == "closeOrderPovRatio":
                    number = _number(text.rstrip("%％"))
                    value = int(number) if number == number.to_integral_value() else float(number)
                elif alias in {"closeOrderAlgoStartTime", "closeOrderAlgoEndTime"}:
                    match = re.fullmatch(r"(\d{1,2})[:：](\d{1,2})", text)
                    if not match or int(match[1]) > 23 or int(match[2]) > 59:
                        raise ValueError("TWAP 时间必须为有效 HH:MM")
                    value = f"{int(match[1]):02d}:{int(match[2]):02d}"
                elif alias == "confirmFullClose":
                    value = (bool(_FULL.search(text)) or text == "全部") and not bool(_KEEP.search(candidate.evidence))
                    # 只有否定全平本身才取消；「全部平仓，不用跟量」里的否定属于其它参数
                    if any(
                        _NEGATED_FULL.search(source)
                        for source in (candidate.evidence, *segments)
                    ):
                        value = False
                row[alias], ledger[alias] = value, _record(value, candidate)
            type_candidate = values.get("closeOrderType")
            inferred = _inferred_order_type(row) if row.get("closeOrderType") is None else None
            order_type = normalize_close_order_type(
                type_candidate.value if type_candidate else None, order_texts=segments, inferred=inferred,
            )
            if order_type is not None:
                row["closeOrderType"] = order_type
                ledger["closeOrderType"] = _record(order_type, type_candidate)
            else:
                row.pop("closeOrderType", None)
                ledger.pop("closeOrderType", None)
            fast_candidate = values.get("hasFastExecutionIntent")
            if (fast_candidate is None or fast_candidate.value is None) and (
                type_candidate and type_candidate.value and is_fast_execution_phrase(type_candidate.value)
            ):
                fast_candidate = type_candidate
            if fast_candidate and fast_candidate.value:
                fast = resolve_fast_execution(
                    "；".join(segments),
                    has_explicit_pov_ratio=row.get("closeOrderPovRatio") is not None,
                )
                row["hasFastExecutionIntent"] = fast
                ledger["hasFastExecutionIntent"] = _record(fast, fast_candidate)
            amount_candidate = values.get("closeOrderNotionalDelta")
            if amount_candidate and amount_candidate.value and _KEEP.search(amount_candidate.value):
                row["confirmFullClose"] = None
                ledger.pop("confirmFullClose", None)
            if row.get("closeOrderType") is None and inferred:
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
