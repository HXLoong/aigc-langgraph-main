"""close 平仓订单号确定性提取 + CO- 正则单一来源（瘦身 P1：4 节点去 LLM 化）。

背景：原 4 个 LLM 节点（close_order_confirm / close_order_cancel_request /
close_order_cancel_confirm / close_order_order_query）的唯一任务是提取 CO- 订单号，
确定性正则 + 引用消息映射即可完成，零幻觉、零成本、零延迟。被替换的 4 个提示词
文件已同批删除。

历史散落的 CO- 正则统一到本模块（单一来源）：
- 用户输入提取 / 校验：ORDER_ID_RE（大小写不敏感，输出统一大写）
- close 消息结构解析（reference_parser.py，Dify 1:1 移植）：
  ORDER_ID_EXACT8_TOKEN（单号：行，严格 8 位十六进制）与
  ORDER_ID_STRICT_TOKEN（8+ 位十六进制，错误 / 全平 / 裸文本提取）

各意图的来源优先级：
- cancel（撤单申请，extract_for_close_orders）：raw 的指定信号（单号 / 第X笔 /
  序号N / 合约编号，取并集）→ 仅取指定订单；无指定信号 → 引用消息全部；均无 → []。
  「第X笔」按引用中出现顺序；「序号N」按引用卡片的序号标签（无标签时按出现顺序）；
  合约编号后紧跟「单号：」时属于其后的单号（Java 平仓卡），否则属于其前的单号。
- confirm / confirm_cancel（最终确认）：走 app/execution/confirmation.py，不用本模块
- query（查单）：仅从 raw 提取全部单号

安全约定（对齐 swap.order_id.extract_for_cancel）：序号越界或合约编号不在引用
消息中时抛 CloseScopeError——宁可请用户补充，也绝不扩大操作范围。
"""
from __future__ import annotations

import re

#: 用户输入中的平仓订单号（CO-YYYYMMDD-XXXXXXXX；大小写不敏感，输出统一大写）
ORDER_ID_RE = re.compile(r"CO-\d{8}-[A-Za-z0-9]{4,16}", re.I)
#: close 消息结构解析（reference_parser）内嵌组合的严格形态（行为与历史一致）
ORDER_ID_EXACT8_TOKEN = r"CO-\d{8}-[0-9A-F]{8}"
ORDER_ID_STRICT_TOKEN = r"CO-\d{8}-[0-9A-F]{8,}"
#: 合约编号（OPT- / OPTG-）
CONTRACT_CODE_RE = re.compile(r"OPT[G]?-[A-Za-z0-9]+")

#: 指定范围无法解析时的统一回复（不扩大操作范围）
SCOPE_UNRESOLVED_REPLY = (
    "无法确定本次操作对应的平仓订单，请补充完整订单号（CO- 开头），"
    "或重新引用订单消息并指定序号。"
)

_NUMBER_CHARS = "零〇一二两三四五六七八九十百"
_CJK_DIGITS = {
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
#: 「第X（笔）」序号词；X 可带单位，或以分隔符 / 动作词 / 结尾收束（排除「第一次」类误命中）
_ORDINAL_RE = re.compile(
    rf"第\s*([{_NUMBER_CHARS}\d]+)\s*"
    rf"(?:[笔个条单]|(?=[、,，和及与\s]|确认|平仓|撤|查|$))"
)
#: 「序号N」显示标签（raw 中按引用卡片的序号标签绑定，而非出现位置）
_SEQ_LABEL_RE = re.compile(rf"序号\s*[:：]?\s*([{_NUMBER_CHARS}\d]+)")
#: Java 平仓卡「合约编号：X\n单号：CO-…」——合约编号与其后的单号同属一笔
_CONTRACT_TO_FOLLOWING_ID_RE = re.compile(r"\s*(?:订单号|单号)\s*[:：]\s*")
#: 纯序号列表（如「1、3」「撤1、3」）在剥离这些词后允许的残余
_BARE_LIST_FILLER_RE = re.compile(
    r"撤单|撤销|撤掉|取消下单|取消|确认撤单|确认平仓|确认|平仓|下单|查单|查询|查|"
    r"好的|可以|没问题|都|全|全部|所有|麻烦|帮我|请|了|吧|呢|的"
)


class CloseScopeError(ValueError):
    """当前操作限定无法由引用消息中的订单信息唯一确定。"""


def extract_order_ids(text: str | None) -> list[str]:
    """按首现顺序提取全部订单号（去重、统一大写）。"""
    if not text:
        return []
    return list(dict.fromkeys(
        match.group(0).upper() for match in ORDER_ID_RE.finditer(text)
    ))


def is_order_id(value: str | None) -> bool:
    """校验 CO- 订单号形态（大小写不敏感）。"""
    return value is not None and ORDER_ID_RE.fullmatch(value.strip()) is not None


def _ordinal_value(token: str) -> int | None:
    """中文数字（≤ 百）/ 阿拉伯数字 → int；无法解析 → None（算法同 swap.order_id）。"""
    if token.isdigit():
        return int(token)
    total = current = 0
    for char in token:
        if char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        elif char in _CJK_DIGITS:
            current = _CJK_DIGITS[char]
        else:
            return None
    return total + current


def _bare_number_targets(raw: str) -> list[int]:
    """纯序号列表（如「1、3」「撤1、3」）→ [1, 3]；正文含其他内容时不识别。"""
    stripped = ORDER_ID_RE.sub(" ", raw)
    stripped = CONTRACT_CODE_RE.sub(" ", stripped)
    stripped = _ORDINAL_RE.sub(" ", stripped)
    stripped = _SEQ_LABEL_RE.sub(" ", stripped)
    stripped = _BARE_LIST_FILLER_RE.sub(" ", stripped)
    if not re.fullmatch(r"[\s\d、,，和及与]*", stripped):
        return []
    return [int(token) for token in re.findall(r"\d+", stripped)]


def _specified_signals(raw: str) -> tuple[list[str], list[int], list[str], list[int]]:
    """从 raw 提取四类指定信号：显式单号 / 位置序号（第X、纯数字列表）/ 合约编号 / 序号标签。"""
    explicit = extract_order_ids(raw)
    ordinals = list(dict.fromkeys(
        value
        for match in _ORDINAL_RE.finditer(raw)
        if (value := _ordinal_value(match.group(1))) is not None
    ))
    ordinals.extend(v for v in _bare_number_targets(raw) if v not in ordinals)
    contracts = [match.group(0).upper() for match in CONTRACT_CODE_RE.finditer(raw)]
    labels = list(dict.fromkeys(
        value
        for match in _SEQ_LABEL_RE.finditer(raw)
        if (value := _ordinal_value(match.group(1))) is not None
    ))
    return explicit, ordinals, contracts, labels


def _label_mapping(quote: str, quote_ids: list[str]) -> dict[int, str | None]:
    """引用消息「序号N」标签 → 单号；标签后到下一个标签前的首个单号归属该标签。

    引用无序号标签时按出现顺序编号（与 app/execution/confirmation.py 一致）；
    同一标签指向不同单号时记为 None（歧义，不可选）。
    """
    markers = list(_SEQ_LABEL_RE.finditer(quote))
    if not markers:
        return {index: oid for index, oid in enumerate(quote_ids, 1)}
    mapping: dict[int, str | None] = {}
    for index, marker in enumerate(markers):
        value = _ordinal_value(marker.group(1))
        end = markers[index + 1].start() if index + 1 < len(markers) else len(quote)
        following = ORDER_ID_RE.search(quote, marker.end(), end)
        if value is None or following is None:
            continue
        oid = following.group(0).upper()
        mapping[value] = oid if mapping.get(value, oid) == oid else None
    return mapping


def _quote_mapping(quote: str) -> tuple[list[str], dict[str, str]]:
    """引用消息 →（首现序单号列表，合约编号 → 所属单号）。

    合约编号后紧跟「单号：」时属于其后的单号（Java 平仓卡版式），
    否则属于其前最近的单号（如「CO-…（OPT-…）」结果卡）。
    """
    positions = [
        (match.start(), match.group(0).upper())
        for match in ORDER_ID_RE.finditer(quote or "")
    ]
    quote_ids = list(dict.fromkeys(order_id for _, order_id in positions))
    contract_map: dict[str, str] = {}
    for match in CONTRACT_CODE_RE.finditer(quote or ""):
        code = match.group(0).upper()
        following = ORDER_ID_RE.search(quote, match.end())
        preceding = [oid for pos, oid in positions if pos < match.start()]
        if following is not None and _CONTRACT_TO_FOLLOWING_ID_RE.fullmatch(
            quote[match.end():following.start()]
        ):
            contract_map.setdefault(code, following.group(0).upper())
        elif preceding:
            contract_map.setdefault(code, preceding[-1])
        elif positions:
            contract_map.setdefault(code, positions[0][1])
    return quote_ids, contract_map


def _resolve_specified(raw: str, quote: str) -> list[str] | None:
    """解析用户指定范围；无任何指定信号 → None；无法解析 → CloseScopeError。"""
    explicit, ordinals, contracts, labels = _specified_signals(raw)
    if not (explicit or ordinals or contracts or labels):
        return None

    quote_ids, contract_map = _quote_mapping(quote)
    label_map = _label_mapping(quote, quote_ids)
    selected: list[str] = list(explicit)
    unresolved = False
    for label in labels:
        label_target = label_map.get(label)
        if label_target is None:
            unresolved = True
        elif label_target not in selected:
            selected.append(label_target)
    for ordinal in ordinals:
        if 1 <= ordinal <= len(quote_ids):
            target = quote_ids[ordinal - 1]
            if target not in selected:
                selected.append(target)
        else:
            unresolved = True
    for code in contracts:
        contract_target = contract_map.get(code)
        if contract_target is None:
            unresolved = True
        elif contract_target not in selected:
            selected.append(contract_target)

    if unresolved:
        raise CloseScopeError(
            f"指定范围无法解析：ordinals={ordinals} labels={labels} contracts={contracts}"
        )

    # 输出顺序对齐引用消息出现序（不在引用中的显式单号保持 raw 序追加在后）
    if quote_ids:
        order_index = {order_id: index for index, order_id in enumerate(quote_ids)}
        selected.sort(
            key=lambda order_id: order_index.get(order_id, len(quote_ids))
        )
    return selected


def extract_for_close_orders(raw: str | None, quote: str | None) -> list[str]:
    """撤单申请：有指定信号 → 仅指定；未指定 → 引用消息全部。"""
    specified = _resolve_specified(raw or "", quote or "")
    if specified is not None:
        return specified
    return extract_order_ids(quote)


def extract_for_query(raw: str | None) -> list[str]:
    """查单：仅从 raw 提取全部单号（原提示词规约）。"""
    return extract_order_ids(raw)


__all__ = [
    "ORDER_ID_RE",
    "ORDER_ID_EXACT8_TOKEN",
    "ORDER_ID_STRICT_TOKEN",
    "CONTRACT_CODE_RE",
    "SCOPE_UNRESOLVED_REPLY",
    "CloseScopeError",
    "extract_order_ids",
    "is_order_id",
    "extract_for_close_orders",
    "extract_for_query",
]
