"""CWAIJY-957 confirmation: exact command plus an unambiguous quoted order scope."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ORDER_ID = r"(?<![A-Za-z0-9-])H-[0-9]{8}-[0-9]{10}(?![A-Za-z0-9-])"
_COMMAND = re.compile(r"序号[1-9][0-9]*(?:、序号[1-9][0-9]*)*，确认下单")
_PAIR = re.compile(
    r"序号[：:]?\s*([0-9]+)\s*(?:单号[：:]\s*|[：:]\s*)(" + ORDER_ID + r")"
    r"|订单(" + ORDER_ID + r")\s*[（(]序号\s*([0-9]+)[）)]"
)
_OTHER_PRODUCT = re.compile(
    r"(?<![A-Za-z0-9-])(?:Q-[0-9]{8}-[0-9]{10}|CO-[0-9]{8}-[0-9A-F]{8}"
    r"|OPTG?-[A-Z]{4,8}[0-9]{6,10})(?![A-Za-z0-9-])"
)
_MESSAGES = {
    "format": "确认指令格式不正确，请按引用订单消息中的提示重新发送。",
    "missing_quote": "请引用包含互换订单号的原订单消息。",
    "ambiguous_quote": "无法确定引用消息中的订单序号，请重新引用原订单消息。",
    "duplicate_sequence": "确认下单序号重复，请检查后重新发送。",
    "unknown_sequence": "确认下单序号超出引用消息的范围，请检查后重新发送。",
}


def is_confirmation(raw: str | None) -> bool:
    text = (raw or "").strip()
    return text == "确认下单" or _COMMAND.fullmatch(text) is not None


@dataclass(frozen=True)
class Confirmation:
    order_ids: tuple[str, ...] = ()
    error: str = ""
    mapping: dict[str, str] = field(default_factory=dict)

    def correction(self) -> str:
        if not self.error:
            return ""
        lines = [_MESSAGES[self.error]]
        if self.mapping:
            lines.extend(f"序号{seq}:{order_id}" for seq, order_id in self.mapping.items())
            lines.extend([
                "如所有订单无误，请引用本消息回复【确认下单】。",
                "如只确认部分订单，请引用本消息回复【序号x、序号x，确认下单】，例如【序号2、序号4，确认下单】；该指令将直接提交所选订单。",
            ])
        else:
            lines.append("请引用原订单消息，全部确认回复【确认下单】，部分确认回复【序号2、序号4，确认下单】（按原订单实际序号填写）。")
        lines.append("如需指定部分订单，序号之间使用中文顿号“、”，最后使用中文逗号“，确认下单”。")
        return "\n".join(lines)


def parse_confirmation(raw: str | None, quote: str | None) -> Confirmation:
    """Only explicit quote pairs select orders; malformed scope never becomes 'all'."""
    text, reference = (raw or "").strip(), quote or ""
    if not is_confirmation(text):
        return Confirmation(error="format")
    ids = tuple(dict.fromkeys(re.findall(ORDER_ID, reference)))
    mapping: dict[str, str] = {}
    ambiguous = bool(_OTHER_PRODUCT.search(reference))
    for match in _PAIR.finditer(reference):
        seq, order_id = (match[1], match[2]) if match[1] else (match[4], match[3])
        if not re.fullmatch(r"[1-9][0-9]*", seq):
            ambiguous = True
        if seq in mapping and mapping[seq] != order_id:
            ambiguous = True
        if order_id in mapping.values() and mapping.get(seq) != order_id:
            ambiguous = True
        mapping[seq] = order_id
    complete = set(mapping.values()) == set(ids)
    safe_mapping = mapping if not ambiguous and complete else {}
    if not ids:
        return Confirmation(error="missing_quote", mapping=safe_mapping)
    if ambiguous:
        return Confirmation(error="ambiguous_quote")
    if text == "确认下单":
        return Confirmation(order_ids=ids, mapping=safe_mapping)
    if not complete:
        return Confirmation(error="ambiguous_quote")
    sequences = [item[2:] for item in text.split("，")[0].split("、")]
    if len(sequences) != len(set(sequences)):
        return Confirmation(error="duplicate_sequence", mapping=safe_mapping)
    if any(seq not in mapping for seq in sequences):
        return Confirmation(error="unknown_sequence", mapping=safe_mapping)
    return Confirmation(order_ids=tuple(mapping[seq] for seq in sequences), mapping=safe_mapping)
