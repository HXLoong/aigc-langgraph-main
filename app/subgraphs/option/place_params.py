"""option 请求下单 / 确认下单 的确定性参数提取（替代 LLM 节点）。

行为 1:1 对照原提示词（`option/extract_place.md`、`option/extract_confirm_place.md`）：

- **A 类**（orderType / notionalAmount / limitPrice / povRatio / twap / shortName /
  hasFastExecutionIntent）只取自 raw_content
- **B 类**（orderId / stockCode / optionType / tenor / strikePercentage）
  raw 优先、引用回执（quote_content）兜底；期权类型卡校验收窄为 3 值枚举
- orderType 关键词优先级：TWAP > POV（含"跟量"）> 限价单 > 市价单，与出现顺序无关
- hasFastExecutionIntent 仅当出现快速执行关键词时 true；普通跟量 / 跟量+比例 → false
- 名义本金换算复用 `normalize.py`（与询价链路同口径：1kw = 1万）

产出为 partial dict（snake_case），由节点经 Pydantic 容器校验后补齐为完整字段集。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.subgraphs.option.normalize import normalize_notional
from app.subgraphs.option.order_id import extract_order_ids

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
_SHORT_NAME_STOP_RE = re.compile(r"[\r\n；;，,。！!？?]+")
_SHORT_NAME_ACTION_SPLIT_RE = re.compile(r"(?=\s(?:市价|限价|POV|pov|TWAP|twap|下单|操作|确认))")
_MENTION_RE = re.compile(r"@\S+")
_LETTER_RE = re.compile(r"(?<![A-Za-z0-9-])([A-Z])(?![A-Za-z0-9-])")
#: 上下文列表条目（"A.临沂阿凡提 B.11125测试短名(张天琪专用)"）
_LETTER_ITEM_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z])[.、）)]\s*(.+?)(?=\s+[A-Z][.、）)]|[\r\n；;，,]|$)"
)

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


def _extract_short_name(raw: str, context: str) -> str | None:
    for match in _OPP_LABEL_RE.finditer(raw):
        cleaned = _clean_short_name(match.group(1))
        if cleaned:
            return cleaned
    own_match = _OPP_BARE_ACCOUNT_RE.search(raw)
    if own_match:
        cleaned = _clean_short_name(own_match.group(1))
        if cleaned:
            return cleaned
    letters = {m.group(1) for m in _LETTER_RE.finditer(_MENTION_RE.sub(" ", raw))}
    if len(letters) == 1:
        return _resolve_letter(letters.pop(), context)
    return None


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
    cleaned = _PARTICIPATION_RE.sub(" ", raw or "")
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


def _reference_fields(raw: str, quote: str) -> dict[str, Any]:
    """B 类字段：raw 优先，引用回执兜底。"""
    ids = extract_order_ids(raw) or extract_order_ids(quote) or [None]

    stock_code = (
        _raw_stock_code(raw)
        or _labeled(raw, "标的代码")
        or _labeled(raw, "标的名称")
        or _labeled(quote, "标的代码")
        or _labeled(quote, "标的名称")
    )

    option_type = _token_option_type(raw)
    if option_type is None:
        card_type = _labeled(quote, "期权类型")
        option_type = _token_option_type(card_type) if card_type else None
        if option_type is None:
            option_type = _token_option_type(quote)

    tenor = _raw_tenor(raw)
    if tenor is None:
        value = _labeled(quote, "期限")
        if value:
            match = re.match(r"(\d+(?:\.\d+)?)\s*([MYWmyw])", value)
            if match:
                tenor = f"{match.group(1)}{match.group(2).upper()}"

    strike = _raw_strike(raw)

    return {
        "order_ids": ids,
        "stock_code": stock_code,
        "option_type": option_type,
        "tenor": tenor,
        "strike_percentage": strike if strike is not None else _card_strike(quote),
    }


def history_texts(messages: Sequence[Any] | None) -> list[str]:
    """历史消息 → 文本列表（供交易对手选项字母上下文回退）。"""
    return [msg.content for msg in messages or [] if getattr(msg, "content", None)]


def parse_place_params(
    raw: str | None,
    quote: str | None,
    history_texts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """请求下单（place_order_from_quote）的订单条目（partial dict，含 hasFastExecutionIntent）。"""
    raw_text = raw or ""
    quote_text = quote or ""
    context = "\n".join(text for text in (quote_text, *history_texts) if text)

    order_type = _extract_order_type(raw_text)
    twap_start, twap_end = (
        _extract_twap_times(raw_text) if order_type == "TWAP" else (None, None)
    )
    common: dict[str, Any] = {
        "notional_amount": normalize_notional(raw_text),
        "order_type": order_type,
        "limit_price": _extract_limit_price(raw_text),
        "pov_ratio": _extract_pov_ratio(raw_text) if order_type == "POV" else None,
        "twap_start_time": twap_start,
        "twap_end_time": twap_end,
        "short_name": _extract_short_name(raw_text, context),
    }
    fast_execution = _extract_fast_execution(raw_text)
    reference = _reference_fields(raw_text, quote_text)

    items: list[dict[str, Any]] = []
    for order_id in reference["order_ids"]:
        items.append({
            "order_id": order_id,
            "stock_code": reference["stock_code"],
            "option_type": reference["option_type"],
            "tenor": reference["tenor"],
            "strike_percentage": reference["strike_percentage"],
            "has_fast_execution_intent": fast_execution,
            **common,
        })
    return items


def parse_confirm_place_params(
    raw: str | None,
    quote: str | None,
    history_texts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """确认下单（confirm_order）的订单条目（A 类不含 hasFastExecutionIntent）。"""
    raw_text = raw or ""
    quote_text = quote or ""
    context = "\n".join(text for text in (quote_text, *history_texts) if text)

    order_type = _extract_order_type(raw_text)
    twap_start, twap_end = (
        _extract_twap_times(raw_text) if order_type == "TWAP" else (None, None)
    )
    common: dict[str, Any] = {
        "notional_amount": normalize_notional(raw_text),
        "order_type": order_type,
        "limit_price": _extract_limit_price(raw_text),
        "pov_ratio": _extract_pov_ratio(raw_text) if order_type == "POV" else None,
        "twap_start_time": twap_start,
        "twap_end_time": twap_end,
        "short_name": _extract_short_name(raw_text, context),
    }
    reference = _reference_fields(raw_text, quote_text)

    return [
        {
            "order_id": order_id,
            "stock_code": reference["stock_code"],
            "option_type": reference["option_type"],
            "tenor": reference["tenor"],
            "strike_percentage": reference["strike_percentage"],
            **common,
        }
        for order_id in reference["order_ids"]
    ]


__all__ = ["history_texts", "parse_confirm_place_params", "parse_place_params"]
