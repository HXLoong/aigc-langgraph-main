"""Constrain model claims to the current operation and explicit source windows."""
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.extraction.fields import EvidenceError
from app.subgraphs.swap.errors import AmbiguousActionError, NonPositiveQuantityError
from app.subgraphs.swap.normalize import (
    PREMARKET_WORDS,
    has_market_requirement,
    holding_action,
    is_holding_description,
    negates_token,
    normalize_field,
)

_ORDER_ID = re.compile(r"H-[0-9]{8}-[0-9]+")
_TERMINATOR = re.compile(r"[,，]\s*全部清仓(?=$|\s|[,，。;；!?！？])")


def _within(cell: Any, text: str) -> bool:
    return isinstance(cell, dict) and bool(cell.get("value")) and bool(cell.get("evidence")) and cell["evidence"] in text


def _constrain_references(candidates: BaseModel, sources: Mapping[str, str]) -> BaseModel:
    data = candidates.model_dump(by_alias=True)
    orders = data.get("orderList") or []
    raw, quote = sources.get("raw", ""), sources.get("quote", "")
    if _ORDER_ID.search(quote):
        for order in orders:
            for field, cell in order.items():
                if field not in {"orderId", "placeOrderUltraContractCode"} and cell and cell.get("origin") != "raw":
                    order[field] = None
            # Bare option/number replies are interpreted by the explicit selection chain.
            if re.fullmatch(r"[0-9]+|[A-Za-z](?:[、,，\s]+[A-Za-z])*", raw.strip()):
                order["placeOrderWindCode"] = None
        return type(candidates).model_validate(data)
    match = _TERMINATOR.search(raw)
    if not match:
        return candidates
    prefix = raw[:match.start()]
    eligible = [order for order in orders if any(
        _within(order.get(field), prefix) for field in ("placeOrderQuantity", "placeOrderNotional")
    ) and all(
        not order.get(field) or _within(order[field], prefix)
        for field in ("placeOrderWindCode", "placeOrderOrderDirection")
    )]
    if len(eligible) < 2:
        return candidates
    for order in eligible:
        for field, cell in order.items():
            if field != "placeOrderShortname" and cell and not _within(cell, prefix):
                order[field] = None
    data["orderList"] = eligible
    return type(candidates).model_validate(data)


_ACTION_FIELDS = {"placeOrderOrderDirection", "placeOrderCloseIntent", "placeOrderEntrustRatio"}
_SCOPED_FIELDS = _ACTION_FIELDS | {"placeOrderAlgorithmType", "placeOrderPovPercent", "placeOrderTotalPovPercent"}
_EXECUTION_ANCHORS = ("placeOrderPremarket", "hasFastExecutionIntent", "placeOrderPrice")
_ACTION_PREFIX = re.compile(
    r"买入|卖出|買入|賣出|卖空|賣空|沽出|沽|做多|做空|平多|平空|买|卖|買|賣|"
    r"(?<![A-Za-z])(?:BUY|SELL|SHORT_OPEN|SHORT_CLOSE)(?![A-Za-z])", re.I,
)
_NATURAL_WINDOWS = {"全天", "开盘", "到收盘", "至收盘", "收盘"}
_NON_CURRENT_ACTION = re.compile(
    r"(?:已改|已|暂|暫){1,2}(?:买入|買入|卖出|賣出|买|買|卖|賣|沽出|沽|入)"
    r"|(?:买入|買入|卖出|賣出|买|買|卖|賣|沽出|沽)了",
)


def _name_spans(row: dict[str, Any], text: str) -> list[tuple[int, int]]:
    names = [row.get(field) for field in ("placeOrderWindCode", "placeOrderShortname")]
    return [match.span() for name in names if name and name.get("value")
            for match in re.finditer(re.escape(name["value"]), text)]


def _outside_names(value: str, row: dict[str, Any], text: str) -> bool:
    spans = _name_spans(row, text)
    return any(not any(start <= match.start() and match.end() <= end for start, end in spans)
               for match in re.finditer(re.escape(value), text))


def _timing_roles(row: dict[str, Any], raw: str) -> list[str]:
    """明确盘前词可以纠正字段归属；随后仍校验同笔证据、否定与条件。"""
    misplaced = []
    for field in ("placeOrderPriceType", "placeOrderTransactionType"):
        candidate = row.get(field)
        if (not candidate or candidate.get("origin", "raw") != "raw"
                or candidate.get("value") not in PREMARKET_WORDS):
            continue
        if field == "placeOrderTransactionType" and has_market_requirement(raw):
            continue
        if not _outside_names(candidate["value"], row, raw):
            raise EvidenceError("盘前词只出现在标的或对手名称中")
        current = row.get("placeOrderPremarket")
        if not current or current.get("origin", "raw") != "raw":
            row["placeOrderPremarket"] = dict(candidate)
        elif current.get("value") not in PREMARKET_WORDS:
            raise ValueError("盘前候选存在冲突，不能自动合并")
        misplaced.append(field)
    return misplaced


def _omit_duplicate_market_role(
    row: dict[str, Any], window: str, *, market_explicit: bool,
) -> None:
    market = row.get("placeOrderTransactionType")
    if (market_explicit or not market or market.get("origin", "raw") != "raw"
            or not market.get("value")):
        return
    value = market["value"]
    qualifiers = window.replace("不限价", "").replace("不限價", "")
    if not _outside_names(value, row, window) or re.search(
        r"[不未没勿别]|禁止|无需|無需|如果|假如|若|或者|或|达到.*再|等.*再|已|完成"
        r"|\b(?:not|no|never)\b", qualifiers, re.I,
    ):
        return
    for field in ("placeOrderOrderDirection", "placeOrderPriceType", "placeOrderAlgorithmType"):
        candidate = row.get(field)
        if (candidate and candidate.get("origin", "raw") == "raw"
                and (candidate.get("value") or "").casefold() == value.casefold()
                and _within(candidate, window)):
            # 只去掉已有合法字段的重复误填，不从市场字段创造新买卖动作或算法。
            normalize_field(field, candidate["value"], candidate["evidence"])
            row["placeOrderTransactionType"] = None
            return


def _single_order_block(row: dict[str, Any], raw: str) -> str | None:
    anchor = row.get("placeOrderWindCode") or row.get("orderId")
    clauses = re.split(r"[;；]", raw)
    if len(clauses) == 1:
        block = raw
    elif anchor and anchor.get("value"):
        matches = [clause for clause in clauses if anchor["value"] in clause]
        if len(matches) != 1:
            return None
        block = matches[0]
    else:
        return None
    if "\n" not in block:
        return block
    literals = {cell["value"].strip() for field, cell in row.items()
                if field not in _SCOPED_FIELDS and cell and cell.get("value")}
    for line in block.splitlines():
        text = line.strip()
        if not text or text in literals or (anchor and anchor.get("value") and anchor["value"] in text):
            continue
        if re.match(r"(?:交易)?标的\s*[:：]", text):
            raise EvidenceError("another instrument label occurs in a single order block")
        if re.match(r"(?:(?:交易)?(?:方向|数量(?:/金额)?|金额|股数|价格|方式)|建仓方式|备注)\s*[:：]", text):
            continue
        if re.fullmatch(r"(?:新增|交易|下单)?指令[:：]?|买入|卖出|買入|賣出|市价|不限价|限价\s*[0-9.]+", text):
            continue
        raise EvidenceError("unattributed line in a single order block")
    return block


def _order_window(row: dict[str, Any], orders: list[dict[str, Any]], raw: str) -> str | None:
    if len(orders) == 1:
        return _single_order_block(row, raw)
    positions = []
    anchors = ("placeOrderWindCode", "placeOrderQuantity", "placeOrderNotional", "orderId", *_EXECUTION_ANCHORS)
    for order in orders:
        candidates = []
        for field in anchors:
            anchor = order.get(field)
            if not anchor or anchor.get("origin", "raw") != "raw" or not anchor.get("value"):
                continue
            value = anchor["value"]
            if sum(bool(other.get(field)) and other[field].get("value") == value for other in orders) != 1:
                continue
            matches = list(re.finditer(re.escape(value), raw))
            if len(matches) == 1:
                candidates.append((matches[0].start(), field))
        if not candidates:
            return None
        position, field = min(candidates)
        positions.append((position, order, field))
    positions.sort(key=lambda item: item[0])
    starts = []
    for index, (position, order, anchor_field) in enumerate(positions):
        start = 0 if index == 0 else position
        if index:
            boundary = max(raw.rfind(char, 0, position) for char in ";；\n,，") + 1
            hard_boundary = max(raw.rfind(char, 0, position) for char in ";；\n") + 1
            prefix = raw[boundary:position].strip()
            if hard_boundary > positions[index - 1][0]:
                start = hard_boundary
            elif re.search(r"不|别|勿|禁止|无需|如果|假如|若", prefix) or (
                anchor_field != "placeOrderWindCode" and boundary > positions[index - 1][0]
            ) or re.fullmatch(
                r"(?:(?:新增指令[:：])?标的[:：]|(?:再|另|另外|其余|剩余)?(?:买入|卖出|卖空|平仓)?\s*)", prefix,
            ):
                start = boundary
            else:
                for match in re.finditer(r"其余|另外|剩余", raw[positions[index - 1][0]:position]):
                    start = positions[index - 1][0] + match.start()
            # 紧凑订单可先写动作和数量、再写标的；保留本笔紧邻锚点的动作。
            actions = list(_ACTION_PREFIX.finditer(raw[:position]))
            if actions and not raw[actions[-1].end():position].strip():
                action_start = actions[-1].start()
                if positions[index - 1][0] < action_start < start:
                    start = action_start
        starts.append((start, order))
    if len({start for start, _ in starts}) != len(starts):
        return None
    for index, (start, order) in enumerate(starts):
        if order is row:
            end = starts[index + 1][0] if index + 1 < len(starts) else len(raw)
            return raw[start:end].strip(";；\n,， ")
    return None


def _shared_direction_prefix(orders: list[dict[str, Any]], raw: str) -> str | None:
    """A single leading action can govern a list; later actions end that inference."""
    if len(orders) < 2:
        return None
    directions = [row.get("placeOrderOrderDirection") for row in orders]
    if any(not cell or cell.get("origin", "raw") != "raw" for cell in directions):
        return None
    if len({cell.get("value") for cell in directions if cell is not None}) != 1:
        return None
    positions = []
    for row in orders:
        anchor = row.get("placeOrderWindCode") or row.get("orderId")
        if not anchor or not anchor.get("value") or anchor["value"] not in raw:
            return None
        positions.append(raw.index(anchor["value"]))
    boundary = min(positions)
    prefix = raw[:boundary]
    direction = directions[0]
    if (not direction or direction.get("value") not in prefix
            or _ACTION_PREFIX.search(raw[boundary:])
            or re.search(r"如果|假如|若|或者|否则", prefix)):
        return None
    return prefix


def constrain_candidates(candidates: BaseModel, sources: Mapping[str, str]) -> BaseModel:
    """Exclude descriptive claims; only unambiguous current-order evidence can bind actions."""
    candidates = _constrain_references(candidates, sources)
    data = candidates.model_dump(by_alias=True)
    orders = data.get("orderList") or []
    market_explicit = has_market_requirement(sources.get("raw", ""))
    timing_roles = [_timing_roles(row, sources.get("raw", "")) for row in orders]
    shared_direction = _shared_direction_prefix(orders, sources.get("raw", ""))
    for index, row in enumerate(orders):
        market = row.get("placeOrderTransactionType")
        instrument = row.get("placeOrderWindCode")
        if market and market.get("origin", "raw") == "raw":
            if not market_explicit and market.get("value") in {"互换", "收益互换", "场外收益互换"}:
                row["placeOrderTransactionType"] = None
            elif (not market_explicit and instrument and _within(market, instrument.get("value") or "")
                  and any(market.get("value", "").lstrip(".").casefold() == suffix.casefold()
                          for suffix in re.findall(r"\.([A-Za-z]+)", instrument.get("value") or ""))):
                try:
                    normalize_field("placeOrderTransactionType", market.get("value") or "")
                except ValueError:
                    # 代码内的交易所后缀不是用户选择的交易品种，不推断市场。
                    row["placeOrderTransactionType"] = None
        for field in _ACTION_FIELDS:
            candidate = row.get(field)
            if candidate and candidate.get("origin") in {"quote", "history"}:
                row[field] = None
        window = _order_window(row, orders, sources.get("raw", ""))
        if window is None:
            if any(row.get(field) and row[field].get("origin", "raw") == "raw" for field in _SCOPED_FIELDS):
                raise EvidenceError("cannot establish a unique source window for order actions")
            continue
        scoped_fields = _SCOPED_FIELDS | set(_EXECUTION_ANCHORS) if len(orders) > 1 else _SCOPED_FIELDS
        for field in scoped_fields:
            candidate = row.get(field)
            if (candidate and candidate.get("origin", "raw") == "raw"
                    and candidate.get("value") and not _within(candidate, window)):
                if field == "placeOrderOrderDirection" and shared_direction is not None:
                    continue
                raise EvidenceError(f"{field}: action evidence does not belong to this order")
        for field in timing_roles[index]:
            premarket = row["placeOrderPremarket"]
            if not _within(premarket, window):
                raise EvidenceError("盘前证据不属于当前订单")
            premarket["evidence"] = window
            row[field] = None
        _omit_duplicate_market_role(row, window, market_explicit=market_explicit)
        for field in ("placeOrderQuantity", "placeOrderQuantityHand", "placeOrderQuantityTotal", "placeOrderDisplayQty"):
            candidate = row.get(field)
            value = candidate.get("value") if candidate else None
            token = value.lstrip() if isinstance(value, str) else ""
            if (re.match(r"[+]?[0-9]", token)
                    and re.search(r"(?<![A-Za-z0-9_.-])(?:[-−]\s*)+" + re.escape(token) + r"(?![0-9.])", window)):
                raise NonPositiveQuantityError(field)
        direction = row.get("placeOrderOrderDirection")
        if (direction and direction.get("value") and not is_holding_description(direction["value"])
                and not _outside_names(direction["value"], row, shared_direction or window)):
            raise EvidenceError("买卖动作只出现在标的或对手名称中")
        name_spans = _name_spans(row, window)
        for match in _NON_CURRENT_ACTION.finditer(window):
            if not any(start <= match.start() and match.end() <= end for start, end in name_spans):
                raise AmbiguousActionError()
        if direction and is_holding_description(direction.get("value") or ""):
            row["placeOrderOrderDirection"] = None
        elif direction and direction.get("value") and negates_token(
            direction["value"], shared_direction or window,
        ):
            raise ValueError("交易方向被否定")
        close = row.get("placeOrderCloseIntent")
        if close and close.get("origin", "raw") == "raw":
            if is_holding_description(close.get("value") or "") and holding_action(window) is None:
                row["placeOrderCloseIntent"] = None
            else:
                close["evidence"] = window
        ratio = row.get("placeOrderEntrustRatio")
        if ratio and ratio.get("origin", "raw") == "raw" and is_holding_description(ratio.get("value") or ""):
            action = holding_action(window)
            if action is not True:
                row["placeOrderEntrustRatio"] = None
            else:
                ratio["evidence"] = window
        algorithm = row.get("placeOrderAlgorithmType")
        if (algorithm and algorithm.get("origin", "raw") == "raw" and algorithm.get("value")
                and negates_token(algorithm["value"], window)):
            raise ValueError("算法表达被否定")
        for field in ("placeOrderStartTime", "placeOrderEndTime", "placeOrderRelativeTimeMinutes"):
            candidate = row.get(field)
            if (candidate and candidate.get("origin", "raw") == "raw"
                    and candidate.get("value") in _NATURAL_WINDOWS and _within(candidate, window)):
                row[field] = None
    return type(candidates).model_validate(data)
