"""swap.refine_quote_hints · 互换-规整引用补参摘要（Dify code 节点 1:1 移植）。

把机器人上一条"订单详情+请补充参数"消息剥成"订单号(多单含序号) + 该单待补字段名列表"，
剥掉订单详情正文、"匹配到其他标的"候选列表、候选交易对手选项(交易对手由专门节点处理)。
无补参内容时降级为空串，不误伤全新下单/确认下单。

同时对 raw_content 做确定性数字标注（价格关键词/@ 后数字按限价、其余英文逗号整数按
委托数量），供 swap.place_order 的 LLM 下单节点消费（对应 Dify 变量
`raw_content_for_llm` / `quote_param_hints`）。

纯函数、无 IO——1:1 对照
`/private/tmp/.../spec/code_nodes/互换-规整引用补参摘要.py`。
"""
from __future__ import annotations

import re
from typing import TypedDict

SWAP_ORDER = r"H-\d{8}-\d{10}"
HINT_MARK = "【请补充参数："
HINT = re.compile(r"【请补充参数：([^】]+)】")
# 回退: 详情行「X：【待补充】」也视为待补字段(兼容不带【请补充参数：X】块的消息变体)
PEND_LINE = re.compile(r"([一-龥A-Za-z/／]{2,8})：【待补充】")
# 多订单补参表头: "订单{订单号}(序号N)：" —— 容错全/半角括号与空格; 序号缺失时由 SEQ_PAIR 兜底
MULTI_HEAD = re.compile(r"订单\s*(" + SWAP_ORDER + r")\s*(?:[（(]\s*序号\s*(\d+)\s*[）)])?")
SOLE_ID = re.compile(r"单号[:：]\s*(" + SWAP_ORDER + r")")
# 详情区 "序号：N 单号：H-..." 配对, 作为表头无序号时的兜底来源
SEQ_PAIR = re.compile(r"序号[:：]\s*(\d+)\s*单号[:：]\s*(" + SWAP_ORDER + r")")
CLOSE_OPT = re.compile(r"第\d+笔[:：][^第【】]*?（[^）]+）")

# 同一字段的后端双名归一: 字段统一为"可见委托量"；FIELD_ALIAS 仅把历史消息旧名"可委托数量"归一到"可见委托量"(同指 placeOrderDisplayQty)
FIELD_ALIAS = {"可委托数量": "可见委托量"}

GLUED_ALPHA_SHARE_QUANTITY = re.compile(
    r"(?<![A-Za-z0-9.])"
    r"(?P<symbol>[A-Za-z]{1,5}(?:\.[A-Za-z]{1,2})?)"
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>万|千|亿|k|K|w|W)?\s*"
    r"(?P<unit>股|份)(?![A-Za-z])",
    re.I,
)
EXPLICIT_QUANTITY = re.compile(
    r"(?<![A-Za-z0-9.])(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>万|千|亿|k|K|w|W)?\s*"
    r"(?P<unit>股|手|张|份|lot|lots)(?![A-Za-z])",
    re.I,
)
QUANTITY_SCALE = {"千": 1000, "k": 1000, "万": 10000, "w": 10000, "亿": 100000000}

COMMA_INTEGER_TOKEN = r"(?<![A-Za-z0-9.])\d[\d,]*,\d[\d,]*(?![A-Za-z0-9.])"
COMMA_INTEGER = re.compile(COMMA_INTEGER_TOKEN)
LIMIT_COMMA_INTEGER = re.compile(
    r"(?:(?<!不设)(?<!不)(?<!无)限价(?:委托)?|(?<!不)(?<!无)限定价格|"
    r"(?<!不)(?<!无)(?<!限定)(?<!限制)价格|均价|均價|(?i:LimitOrder))\s*"
    r"(?P<value>" + COMMA_INTEGER_TOKEN + r")"
)
AT_PRICE_NUMBER = re.compile(r"@\s*(?P<value>\d[\d,]*(?:\.\d+)?)")
LIMIT_BEFORE_QUANTITY_MARKER = re.compile(
    r"(?<!不设)(?<!不)(?<!无)(?:限价(?:委托)?|限定价格|价格)\s*(?=【委托数量：)"
)


class QuoteHints(TypedDict):
    quote_param_hints: str
    raw_content_for_llm: str


def _number_value(token: str) -> str:
    return token.replace(",", "")


def _normalize_raw_content(raw_content: str | None) -> str:
    """确定性标注易混数字：价格关键词/@ 后数字按限价；其余英文逗号整数按委托数量。"""
    raw = str(raw_content or "")

    def replace_glued_alpha_share_quantity(match: re.Match[str]) -> str:
        value = float(_number_value(match.group("value")))
        scale_token = match.group("scale") or ""
        scale = QUANTITY_SCALE.get(scale_token.lower(), 1)
        quantity = value * scale
        if not quantity.is_integer():
            return match.group(0)
        return match.group("symbol") + "【委托数量：" + str(int(quantity)) + "；数量单位：SHARE】"

    def replace_explicit_quantity(match: re.Match[str]) -> str:
        value = float(_number_value(match.group("value")))
        scale_token = match.group("scale") or ""
        scale = QUANTITY_SCALE.get(scale_token.lower(), 1)
        quantity = value * scale
        if not quantity.is_integer():
            return match.group(0)
        unit = "HAND" if match.group("unit").lower() in {"手", "张", "lot", "lots"} else "SHARE"
        return "【委托数量：" + str(int(quantity)) + "；数量单位：" + unit + "】"

    def replace_at_price(match: re.Match[str]) -> str:
        price = _number_value(match.group("value"))
        return "【价格类型：LimitOrder；限定价格：" + price + "】"

    def replace_limit(match: re.Match[str]) -> str:
        price = _number_value(match.group("value"))
        return "【价格类型：LimitOrder；限定价格：" + price + "】"

    def replace_quantity(match: re.Match[str]) -> str:
        prefix = raw[max(0, match.start() - 8):match.start()]
        if re.search(r"(?:不设限价|不限价|无限价|不限定价格|不限制价格)\s*$", prefix):
            return match.group(0)
        return "【委托数量：" + _number_value(match.group(0)) + "】"

    # 纯字母美股代码紧贴股数时，单位"股/份"确定数字全部属于数量，例如 TSM2625股。
    raw = GLUED_ALPHA_SHARE_QUANTITY.sub(replace_glued_alpha_share_quantity, raw)
    # 明确股/手单位的数量优先级最高；先保护后，前面的"限价"只表示价格类型，不抢占数量。
    raw = EXPLICIT_QUANTITY.sub(replace_explicit_quantity, raw)
    # "限价 + 明确数量单位"中，限价只表示价格类型，价格本身仍待补。
    raw = LIMIT_BEFORE_QUANTITY_MARKER.sub("【价格类型：LimitOrder；限定价格：未提供】 ", raw)
    # @数字、限价/价格关键词后的数字都是限价，必须先保护，避免后续逗号整数规则把价格改写成数量。
    raw = AT_PRICE_NUMBER.sub(replace_at_price, raw)
    raw = LIMIT_COMMA_INTEGER.sub(replace_limit, raw)
    return COMMA_INTEGER.sub(replace_quantity, raw)


def _valid(q: str | None) -> bool:
    if not q or not isinstance(q, str):
        return False
    s = q.strip()
    return bool(s) and s.lower() != "null"


def _result(hints: str, raw_content: str | None) -> QuoteHints:
    return {
        "quote_param_hints": hints,
        "raw_content_for_llm": _normalize_raw_content(raw_content),
    }


def _pend_fields(seg: str) -> list[str]:
    fields: list[str] = []
    for f in HINT.findall(seg) + PEND_LINE.findall(seg):
        f = FIELD_ALIAS.get(f, f)
        if f not in fields:
            fields.append(f)
    return fields


def _fmt(oid: str | None, seq: str | None, fields: list[str], close_opts: list[str]) -> list[str]:
    head = "订单 " + oid + ("（序号" + seq + "）" if seq else "") + " " if oid else ""
    out = [head + "需要补充：" + "、".join(fields)]
    out.extend(close_opts)
    return out


def refine_quote_hints(quote_content: str | None, raw_content: str | None = "") -> QuoteHints:
    """互换-规整引用补参摘要：把 quote_content 剥成待补字段摘要 + raw_content 数字标注。

    Args:
        quote_content: 引用的机器人消息（可能为空 / "null"）
        raw_content: 用户本次原始输入

    Returns:
        {"quote_param_hints": str, "raw_content_for_llm": str}
    """
    # 无效引用 -> 空串(全新下单/纯文本)
    if not _valid(quote_content):
        return _result("", raw_content)

    assert quote_content is not None  # for type checkers; _valid() 已排除 None
    # 无补参标记: 引用的是参数齐全订单(或其他含单号消息) -> 输出改参行(只给订单号, 不带任何旧值)
    if HINT_MARK not in quote_content and not PEND_LINE.search(quote_content):
        pairs = SEQ_PAIR.findall(quote_content)
        if pairs:
            lines = [
                "订单 " + oid + "（序号" + seq + "，参数齐全，本次输入按改参处理）"
                for seq, oid in pairs
            ]
        else:
            ids: list[str] = []
            for m in re.finditer(SWAP_ORDER, quote_content):
                if m.group(0) not in ids:
                    ids.append(m.group(0))
            lines = ["订单 " + oid + "（参数齐全，本次输入按改参处理）" for oid in ids]
        return _result("\n".join(lines), raw_content)

    q = quote_content
    seq_map = {oid: seq for seq, oid in SEQ_PAIR.findall(q)}  # 兜底: 订单号 -> 序号
    units: list[list[str]] = []
    heads = list(MULTI_HEAD.finditer(q))
    if heads:
        # 多订单: 按 "订单{订单号}(序号N)" 切片, 详情正文(首个订单头之前)整体丢弃
        covered: set[str] = set()
        for k, m in enumerate(heads):
            stop = heads[k + 1].start() if k + 1 < len(heads) else len(q)
            seg = q[m.start():stop]
            fields = _pend_fields(seg)
            if fields:
                oid = m.group(1)
                seq = m.group(2) or seq_map.get(oid)
                units.append(_fmt(oid, seq, fields, []))
                covered.add(oid)
        # 混合状态: 详情区里参数齐全(无待补段)的订单也输出改参行, 保证引用后可改任意一单
        for seq, oid in SEQ_PAIR.findall(q):
            if oid not in covered:
                units.append(["订单 " + oid + "（序号" + seq + "，参数齐全，本次输入按改参处理）"])
                covered.add(oid)
    else:
        # 单订单 / 平仓持仓选项卡(平仓下单前无订单号)
        oid_m = SOLE_ID.search(q)
        oid = oid_m.group(1) if oid_m else None
        fields = _pend_fields(q)
        close_opts = CLOSE_OPT.findall(q)
        if fields:
            units.append(_fmt(oid, None, fields, close_opts))

    if not units:
        return _result("", raw_content)
    return _result("\n".join("\n".join(u) for u in units).strip(), raw_content)


__all__ = ["refine_quote_hints", "QuoteHints"]
