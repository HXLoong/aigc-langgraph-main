"""option 请求下单 / 确认下单 的确定性参数提取（替代 LLM 节点）。

行为 1:1 对照原提示词（`option/extract_place.md`、`option/extract_confirm_place.md`）：

- **A 类**（orderType / notionalAmount / limitPrice / povRatio / twap / shortName /
  hasFastExecutionIntent）只取自 raw_content
- **B 类**（orderId / stockCode / optionType / tenor / strikePercentage）
  raw 优先、引用回执（quote_content）兜底；期权类型卡校验收窄为 3 值枚举
- orderType 关键词优先级：TWAP > POV（含"跟量"）> 限价单 > 市价单，与出现顺序无关
- hasFastExecutionIntent 仅当出现快速执行关键词时 true；普通跟量 / 跟量+比例 → false
- 名义本金换算复用 `normalize.py`（与询价链路同口径：1kw = 1万）
- **多单分段**（"第一个单 … 第二个单 …"批量补参，case-026）：按显式序号选取引用订单，
  重复或越界直接拒绝，绝不将错误的指定范围广播到全部订单。

产出为 partial dict（snake_case），由节点经 Pydantic 容器校验后补齐为完整字段集。
来源随解析分支一同产生；parse_place_params/parse_confirm_place_params 保留旧返回形态。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.execution.confirmation import only_execution_parameters
from app.extraction.fields import FieldRecord
from app.subgraphs.option.normalize import normalize_notional
from app.subgraphs.option.order_id import ORDER_ID_RE, extract_order_ids

# ============================================================
# A 类：raw 只读
# ============================================================

_FAST_EXEC_KEYWORDS = (
    "最大跟量",
    "积极跟量",
    "尽快成交",
    "快点成交",
    "要快",
    "积极成交",
    "全力成交",
)

_LIMIT_PROBE_RE = re.compile(r"限价")
_LEAD_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")
_UNIT_TAIL_RE = re.compile(r"\s*(?:千万|[Kk][Ww]|亿|万|[Ww]|[Ee]|%)")

_POV_RATIO_RE = re.compile(r"pov\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")

#: 交易对手标签（其后整段为名称候选）
_OPP_LABEL_RE = re.compile(r"(?:交易对手|交易账号|交易账户)\s*[:：]?\s*(.+)")
#: "用账号 12345测试 下单" 式（值后随下单 / 操作）
_OPP_BARE_ACCOUNT_RE = re.compile(r"账号\s*[:：]?\s*(.+?)(?=(?:下单|操作|成交|$))")
#: 交易对手后的选择动词（"交易对手选A / 选择B / 要A"）；剥离后剩单个字母时按选项字母解析
_SELECT_VERB_RE = re.compile(r"^(?:选择|选定|选|要|用)\s*")
_SHORT_NAME_STOP_RE = re.compile(r"[\r\n；;，,。！!？?]+")
_SHORT_NAME_ACTION_SPLIT_RE = re.compile(r"(?=\s(?:市价|限价|POV|pov|TWAP|twap|下单|操作|确认))")
_MENTION_RE = re.compile(r"@\S+")
_LETTER_RE = re.compile(r"(?<![A-Za-z0-9-])([A-Z])(?![A-Za-z0-9-])")
#: 上下文列表条目（"A.临沂阿凡提 B.11125测试短名(张天琪专用)"）
_LETTER_ITEM_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z])[.、）)]\s*(.+?)(?=\s+[A-Z][.、）)]|[\r\n；;，,]|$)"
)

# ============================================================
# 多单分段（"第一个单 … 第二个单 …" 批量补参）
# ============================================================

#: 分段标记：第一个单 / 第2笔 / 第一单 …
_ORDINAL_SEGMENT_RE = re.compile(r"(?:第\s*([一二两三四五六七八九十\d]+)\s*(?:个)?\s*(?:单|笔)|序号\s*[:：]?\s*(\d+))")
_ORDINAL_VALUES = {
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
    "十": 10,
}


class OrderScopeError(ValueError):
    """User-provided order scope cannot be resolved without guessing."""


def _ordinal_number(token: str) -> int | None:
    return int(token) if token.isdigit() else _ORDINAL_VALUES.get(token)


def _split_ordinal_segments(raw: str) -> list[tuple[int, str]]:
    """保留用户指定序号及顺序；重复和无效序号必须纠错。"""
    matches = list(_ORDINAL_SEGMENT_RE.finditer(raw))
    if not matches:
        return []
    if raw[:matches[0].start()].strip(" \t\r\n，,、；;。."):
        raise OrderScopeError("序号前存在无法归属的指令，请分别发送。")
    numbered: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        number = _ordinal_number(match.group(1) or match.group(2))
        if number is None or number < 1:
            raise OrderScopeError("订单序号无效，请按引用中的序号补充参数。")
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        numbered.append((number, raw[start:end].strip(" \t\r\n，,、；;。.")))
    if len({number for number, _ in numbered}) != len(numbered):
        raise OrderScopeError("订单序号重复，请按引用中的序号补充参数。")
    return numbered

# ============================================================
# B 类：raw 优先 → 引用回执兜底
# ============================================================

_RAW_CODE_RE = re.compile(r"(?<![0-9A-Za-z.-])(\d{4,6}\.[A-Za-z]{2,3}|\d{6})(?![0-9A-Za-z.-])")
_RAW_TENOR_RE = re.compile(r"(?<![0-9A-Za-z.])(\d+(?:\.\d+)?)\s*([MY])(?![A-Za-z])")
_PARTICIPATION_RE = re.compile(r"参与(?:率|比例)[^\d\r\n%]{0,4}\d+(?:\.\d+)?\s*%?")
_RAW_STRIKE_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")

#: 卡片标签值的截止条件：下一个标签 / 行尾 / 分隔符
_LABEL_TAIL = (
    r"(?=\s*(?:标的名称|标的代码|期限|期权类型|执行价格|行权价格|行权价|执行价|"
    r"建仓指令|交易对手|单号|订单号|方向|期权费率|到期日|起始日|结算日)\s*[:：%]|[\r\n；;，,]|$)"
)

#: 期权类型枚举（长词优先）
_OPTION_TYPE_TOKENS = ("参与型看涨", "欧式看涨", "雪球", "看涨")


def _extract_order_type(raw: str) -> str | None:
    """关键词优先级：TWAP > POV（含"跟量"）> 限价单 > 市价单，与出现顺序无关。"""
    if re.search(r"twap", raw, re.IGNORECASE):
        return "TWAP"
    if re.search(r"pov", raw, re.IGNORECASE):
        return "POV"
    if "跟量" in raw:
        return "POV"
    if "限价" in raw:
        return "限价单"
    if "市价" in raw:
        return "市价单"
    return None


def _extract_limit_price(raw: str) -> float | None:
    """"限价" 后紧跟的纯数字才是价格；金额表达（100万 / 6.3%）直接跳过。"""
    for probe in _LIMIT_PROBE_RE.finditer(raw):
        rest = raw[probe.end():].lstrip(" \t:：,，、")
        number = _LEAD_NUMBER_RE.match(rest)
        if number is None:
            continue
        if _UNIT_TAIL_RE.match(rest[number.end():]):
            continue
        return float(number.group(1))
    return None


def _extract_pov_ratio(raw: str) -> float | None:
    match = _POV_RATIO_RE.search(raw)
    return float(match.group(1)) if match else None


def _extract_twap_times(raw: str) -> tuple[str | None, str | None]:
    """HH:MM-HH:MM / HH:MM到HH:MM；单时间容错为结束时间；时间补零对齐。"""
    times: list[str] = []
    for match in _TIME_RE.finditer(raw):
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            continue
        times.append(f"{hour:02d}:{minute:02d}")
    if not times:
        return None, None
    if len(times) == 1:
        return None, times[0]
    return times[0], times[1]


def _extract_fast_execution(raw: str) -> bool:
    """仅快速执行关键词为 true；普通跟量 / 跟量+比例 → false。"""
    return any(keyword in raw for keyword in _FAST_EXEC_KEYWORDS)


def _clean_short_name(value: str) -> str | None:
    value = _SHORT_NAME_STOP_RE.split(value)[0]
    value = _SHORT_NAME_ACTION_SPLIT_RE.split(value)[0].strip()
    return value or None


def _resolve_letter(letter: str, context: str) -> str | None:
    for match in _LETTER_ITEM_RE.finditer(context):
        if match.group(1) == letter:
            return _clean_short_name(match.group(2))
    return None


@dataclass(frozen=True)
class SourceText:
    text: str
    origin: str


@dataclass
class ParsedPlaceParams:
    orders: list[dict[str, Any]]
    fields: list[dict[str, FieldRecord]]


def _field(value: Any, source: SourceText) -> FieldRecord:
    return FieldRecord(value=value, source="user", evidence=source.text, origin=source.origin, locked=True)


def _short_name_source(raw: str, contexts: Sequence[SourceText]) -> tuple[str | None, SourceText, str | None]:
    original = SourceText(raw, "raw")

    def letter_value(letter: str) -> tuple[str | None, SourceText, str | None]:
        for source in contexts:
            name = _resolve_letter(letter, source.text)
            if name:
                return name, source, letter
        return None, original, None

    for match in _OPP_LABEL_RE.finditer(raw):
        cleaned = _clean_short_name(match.group(1))
        if not cleaned:
            continue
        letter = _SELECT_VERB_RE.sub("", cleaned).strip()
        if len(letter) == 1 and letter.isalpha():
            selected = letter_value(letter.upper())
            if selected[0]:
                return selected
        return cleaned, original, None
    own_match = _OPP_BARE_ACCOUNT_RE.search(raw)
    if own_match:
        cleaned = _clean_short_name(own_match.group(1))
        if cleaned:
            return cleaned, original, None
    letters = {m.group(1) for m in _LETTER_RE.finditer(_MENTION_RE.sub(" ", raw))}
    if len(letters) == 1:
        return letter_value(letters.pop())
    return None, original, None


def _extract_short_name(raw: str, context: str) -> str | None:
    return _short_name_source(raw, [SourceText(context, "context")])[0]


def _a_class_params(
    text: str, context: str, *, lineage: dict[str, FieldRecord] | None = None,
    contexts: Sequence[SourceText] | None = None,
) -> dict[str, Any]:
    """Capture the selected source at extraction time, before any normalized-value matching."""
    order_type = _extract_order_type(text)
    twap_start, twap_end = _extract_twap_times(text) if order_type == "TWAP" else (None, None)
    short_name, name_source, letter = _short_name_source(
        text, contexts if contexts is not None else [SourceText(context, "context")],
    )
    params = {
        "notional_amount": normalize_notional(text), "order_type": order_type,
        "limit_price": _extract_limit_price(text),
        "pov_ratio": _extract_pov_ratio(text) if order_type == "POV" else None,
        "twap_start_time": twap_start, "twap_end_time": twap_end,
        "short_name": short_name,
    }
    if lineage is not None:
        for key, value in params.items():
            if value is not None:
                lineage[key] = _field(value, name_source if key == "short_name" else SourceText(text, "raw"))
        if letter:
            lineage["short_name.selection"] = _field(letter, SourceText(text, "raw"))
    return params


def _labeled(text: str, label: str) -> str | None:
    """提取 "标签[:：]值" 中的值（截断到下一标签 / 行尾 / 分隔符）。"""
    pattern = re.compile(re.escape(label) + r"%?\s*[:：]\s*(.+?)" + _LABEL_TAIL)
    match = pattern.search(text or "")
    if match is None:
        return None
    value = match.group(1).strip().strip("，,、。；; \t")
    return value or None


def _token_option_type(text: str) -> str | None:
    for token in _OPTION_TYPE_TOKENS:
        if token in (text or ""):
            return "欧式看涨" if token == "看涨" else token
    return None


def _raw_stock_code(raw: str) -> str | None:
    match = _RAW_CODE_RE.search(raw or "")
    return match.group(1) if match else None


def _raw_tenor(raw: str) -> str | None:
    """raw 侧期限仅认 M / Y（W 与"XXW=XX万"金额冲突，交引用回执的期限标签）。"""
    match = _RAW_TENOR_RE.search(raw or "")
    return f"{match.group(1)}{match.group(2).upper()}" if match else None


def _raw_strike(raw: str) -> float | None:
    cleaned = _POV_RATIO_RE.sub(" ", _PARTICIPATION_RE.sub(" ", raw or ""))
    match = _RAW_STRIKE_RE.search(cleaned)
    return float(match.group(1)) if match else None


def _card_strike(text: str) -> float | None:
    for label in ("执行价格", "行权价格", "行权价", "执行价"):
        value = _labeled(text, label)
        if value:
            number = _LEAD_NUMBER_RE.match(value)
            if number:
                return float(number.group(1))
    for segment in re.split(r"[\r\n；;]", text or ""):
        if "费" in segment or "率" in segment:
            continue
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", segment)
        if match:
            return float(match.group(1))
    return None


def _reference_fields(
    raw: str, quote: str, *, lineage: dict[str, FieldRecord] | None = None,
) -> dict[str, Any]:
    """B 类字段：记录实际分支选择，raw 优先、引用回执兜底。"""
    raw_source, quote_source = SourceText(raw, "raw"), SourceText(quote, "quote")

    def select(key: str, choices: list[tuple[Any, SourceText]]) -> Any:
        for value, source in choices:
            if value is not None:
                if lineage is not None:
                    lineage[key] = _field(value, source)
                return value
        return None

    raw_ids, quote_ids = extract_order_ids(raw), extract_order_ids(quote)
    ids: list[str | None] = [*(raw_ids or quote_ids)] or [None]
    if lineage is not None and ids != [None]:
        lineage["order_id"] = _field(ids, raw_source if raw_ids else quote_source)
    stock_code = select("stock_code", [
        (_raw_stock_code(raw), raw_source), (_labeled(raw, "标的代码"), raw_source),
        (_labeled(raw, "标的名称"), raw_source), (_labeled(quote, "标的代码"), quote_source),
        (_labeled(quote, "标的名称"), quote_source),
    ])
    card_type = _labeled(quote, "期权类型")
    option_type = select("option_type", [
        (_token_option_type(raw), raw_source),
        (_token_option_type(card_type) if card_type else None, quote_source),
        (_token_option_type(quote), quote_source),
    ])
    value = _labeled(quote, "期限")
    match = re.match(r"(\d+(?:\.\d+)?)\s*([MYWmyw])", value) if value else None
    tenor = select("tenor", [(_raw_tenor(raw), raw_source),
        (f"{match.group(1)}{match.group(2).upper()}" if match else None, quote_source)])
    strike = select("strike_percentage", [(_raw_strike(raw), raw_source), (_card_strike(quote), quote_source)])
    return {"order_ids": ids, "stock_code": stock_code, "option_type": option_type,
            "tenor": tenor, "strike_percentage": strike}


def history_sources(messages: Sequence[Any] | None) -> list[SourceText]:
    sources = []
    for index, message in enumerate(messages or []):
        content: Any
        ident: Any
        if isinstance(message, str):
            content, ident = message, None
        elif isinstance(message, dict):
            content, ident = message.get("content"), message.get("id")
        else:
            content, ident = getattr(message, "content", None), getattr(message, "id", None)
        if isinstance(content, str) and content:
            sources.append(SourceText(content, f"history:{ident}" if ident else f"history:index:{index}"))
    return sources


def history_texts(messages: Sequence[Any] | None) -> list[str]:
    """兼容旧调用；需要来源的节点直接传历史消息对象。"""
    return [source.text for source in history_sources(messages)]


def quote_blocks_for_order(quote: str, order_id: str | None) -> list[str]:
    """Only read card fields and selection options belonging to this order."""
    matches = list(ORDER_ID_RE.finditer(quote))
    if not order_id or len(extract_order_ids(quote)) <= 1:
        return [quote]
    return [
        quote[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(quote)]
        for index, match in enumerate(matches) if match[0] == order_id
    ]


def is_quoted_batch_supplement(raw: str, quote: str) -> bool:
    """Only an explicit same-product, same-action numbered supplement bypasses planning."""
    if (not extract_order_ids(quote) or re.search(r"(?:H-|CO-)\d{8}-|OPTG?-", quote)
            or re.search(r"确认|确定|询价|撤单|撤销|取消|互换|买入|卖出|然后|如果|成交后", raw)):
        return False
    segments = _split_ordinal_segments(raw)
    if len(segments) < 2:
        return False
    for _, segment in segments:
        params = _a_class_params(segment, quote)
        if not any(value is not None for value in params.values()) or not only_execution_parameters(segment, allow_choice=True):
            return False
    parse_place_params_with_lineage(raw, quote)  # reject duplicate/out-of-range before any submission
    return True


def parse_place_params_with_lineage(
    raw: str | None, quote: str | None, history: Sequence[Any] = (), *, confirm: bool = False,
    selected_order_ids: Sequence[str] | None = None,
) -> ParsedPlaceParams:
    raw_text, quote_text = raw or "", quote or ""
    contexts = [SourceText(quote_text, "quote"), *history_sources(history)]
    reference = _reference_fields(raw_text, quote_text)
    output = ParsedPlaceParams([], [])

    def append(order_id: str | None, text: str, selector: str | None = None) -> None:
        order_blocks = quote_blocks_for_order(quote_text, order_id)
        records: dict[str, FieldRecord] = {}
        order_reference = _reference_fields(text, "", lineage=records)
        for block in order_blocks:
            block_records: dict[str, FieldRecord] = {}
            fields = _reference_fields(text, block, lineage=block_records)
            for key, value in fields.items():
                if key == "order_ids":
                    if "order_id" not in records and "order_id" in block_records:
                        records["order_id"] = block_records["order_id"]
                elif order_reference[key] is None and value is not None:
                    order_reference[key] = value
                    records[key] = block_records[key]
        if "order_id" in records:
            records["order_id"] = records["order_id"].model_copy(update={"value": order_id})
        if selector:
            records["order_id.selection"] = _field(selector, SourceText(selector, "raw"))
        params = _a_class_params(text, "", lineage=records, contexts=[*[SourceText(block, "quote") for block in order_blocks], *[SourceText(line, "quote") for line in quote_text.splitlines() if "本群可选交易对手列表" in line], *contexts[1:]])
        item = {"order_id": order_id, "stock_code": order_reference["stock_code"],
                "option_type": order_reference["option_type"], "tenor": order_reference["tenor"],
                "strike_percentage": order_reference["strike_percentage"], **params}
        if not confirm:
            fast = _extract_fast_execution(text)
            item["has_fast_execution_intent"] = fast
            records["has_fast_execution_intent"] = _field(True, SourceText(text, "raw")) if fast else FieldRecord(
                value=False, source="default", origin="rule:option.fast_execution", locked=True,
            )
        output.orders.append(item)
        output.fields.append(records)

    segments = [] if selected_order_ids is not None else _split_ordinal_segments(raw_text)
    if segments:
        ids = reference["order_ids"]
        if any(number > len(ids) or ids[number - 1] is None for number, _ in segments):
            raise OrderScopeError("订单序号超出引用范围，请重新引用订单消息。")
        selectors = list(_ORDINAL_SEGMENT_RE.finditer(raw_text))
        for (number, segment), selector in zip(segments, selectors, strict=True):
            append(ids[number - 1], segment, selector[0])
    else:
        for order_id in selected_order_ids if selected_order_ids is not None else reference["order_ids"]:
            append(order_id, raw_text)
    return output


def parse_place_params(
    raw: str | None, quote: str | None, history_texts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """兼容原公共函数；业务行为由来源感知的同一解析器实现。"""
    return parse_place_params_with_lineage(raw, quote, history_texts).orders


def parse_confirm_place_params(
    raw: str | None, quote: str | None, history_texts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    return parse_place_params_with_lineage(raw, quote, history_texts, confirm=True).orders


__all__ = ["history_texts", "parse_confirm_place_params", "parse_place_params", "parse_place_params_with_lineage"]
