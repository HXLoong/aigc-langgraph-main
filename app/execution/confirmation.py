"""七条最终确认路径共用的口令与引用范围校验；不读取历史记忆。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.extraction.fields import EvidenceError

ALIASES: dict[str, tuple[str, ...]] = {
    "place": ("确认下单", "确定下单", "确认订单", "下单确认"),
    "cancel": ("确认撤单", "确定撤单", "撤单确认", "确认撤销", "确认取消"),
    "modify": ("确认改单", "确定改单", "改单确认", "确认修改", "确定修改", "修改确认"),
    "close": ("确认平仓", "确定平仓", "平仓确认"),
}
_IDS = re.compile(
    r"(?<![A-Za-z0-9-])(?:H-\d{8}-\d{10}|Q-\d{8}-[A-Za-z0-9]{4,16}|CO-\d{8}-[A-Za-z0-9]{4,16})(?![A-Za-z0-9-])"
)
_CONTRACT = re.compile(r"OPTG?-[A-Za-z0-9]+")
_SEQUENCE = re.compile(
    r"(?:序号\s*[:：]?\s*|第\s*)([+-]?\d+|[零〇一二两三四五六七八九十百]+)(?:\s*(?:个单|个|笔|单(?!号)|条))?"
)
_UNSAFE = re.compile(
    r"[?？]|(?:不|别|没|未|是否|能否|如果|假如|只要|否则|等到|成功后|成交后)|(?:吗|么|嘛)"
)
_PARAMETERS = re.compile(
    r"限价|市价|跟量|pov|twap|\d\s*(?:万|亿|[wW])|名义本金|交易对手|交易账[户号]|\d+\s*[MY]|\d+\s*%|欧式看涨|参与型看涨|雪球",
    re.I,
)
_SEPARATORS = re.compile(r"[\s，,、；;。.!！:：（）()【】\[\]]*")
_ALL = re.compile(r"全部|所有|订单|单号|合约编号|和|及|与")


def confirmation_action(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if _UNSAFE.search(text):
        return None
    if sum(text.count(alias) for aliases in ALIASES.values() for alias in aliases) != 1:
        return None
    matches = [action for action, aliases in ALIASES.items() if any(a in text for a in aliases)]
    return matches[0] if len(matches) == 1 else None


def confirmation_attempt(raw: str | None) -> bool:
    text = (raw or "").strip()
    return text in {"确认", "好的", "可以", "没问题", "-"} or any(
        alias in text for aliases in ALIASES.values() for alias in aliases
    )


def has_execution_parameters(raw: str) -> bool:
    return _PARAMETERS.search(raw) is not None


def only_execution_parameters(text: str, *, allow_choice: bool = False) -> bool:
    if _UNSAFE.search(text) or re.search(
        r"撤单|撤销|取消|改单|确认|确定|查询|询价|然后|平仓|再执行", text
    ):
        return False
    if not has_execution_parameters(text) and not (
        allow_choice and re.fullmatch(r"\s*[A-Z]\s*", text)
    ):
        return False
    rest = re.sub(r"(?:交易对手|交易账[户号])\s*[:：]?[^，,；;\n]+", "", text)
    rest = re.sub(
        r"欧式看涨|参与型看涨|雪球|限价单?|市价(?:单|下单)?|最大跟量|积极跟量|跟量|POV|TWAP|"
        r"名义本金|建仓指令|执行价(?:格)?|行权价(?:格)?|期限",
        "",
        rest,
        flags=re.I,
    )
    rest = re.sub(r"[0-9]+(?:\.[0-9]+)?(?:\.[A-Za-z]{2,3}|千万|万|亿|[wWmMyY]|%|分钟)?", "", rest)
    if allow_choice:
        rest = re.sub(r"(?<![A-Za-z])[A-Z](?![A-Za-z])", "", rest)
    return re.fullmatch(r"[\s，,、；;。.!！:：%/-]*", rest) is not None


def _number(token: str) -> int:
    if token.lstrip("+-").isdigit():
        return int(token)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    total = current = 0
    for char in token:
        if char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            current = digits[char]
    return total + current


@dataclass(frozen=True)
class Confirmation:
    order_ids: tuple[str, ...] = ()
    error: str = ""
    mapping: dict[str, str] = field(default_factory=dict)
    action: str = "place"

    def verify_scope(self, order_ids: Sequence[str | None]) -> None:
        """Validate again after provenance locks, before a backend can see the DTO."""
        if tuple(order_ids) != self.order_ids:
            raise EvidenceError("确认订单范围与锁定字段冲突，本次未提交，请重新引用订单消息。")

    def correction(self) -> str:
        if not self.error:
            return ""
        command = ALIASES[self.action][0]
        lines = ["我暂时无法识别您的指令。"]
        lines.extend(f"序号{seq}:{oid}" for seq, oid in self.mapping.items())
        if len(self.mapping) == 1:
            lines.append(f"如订单无误，请引用本消息回复【{command}】。")
        elif self.mapping:
            lines.extend(
                [
                    f"如所有订单无误，请引用本消息回复【{command}】。",
                    f"如只确认部分订单，请引用本消息回复【序号x、序号x，{command}】，例如【序号2、序号4，{command}】；该指令将直接提交所选订单。",
                ]
            )
        else:
            lines.append(
                f"请引用原订单消息，全部确认回复【{command}】，部分确认请指定原订单实际序号。"
            )
        return "\n".join(lines)


def parse_confirmation(
    raw: str | None,
    quote: str | None,
    *,
    product: str = "swap",
    action: str = "place",
    allow_parameters: bool = False,
) -> Confirmation:
    text = re.sub(r"^(?:@\S+\s+)+", "", (raw or "").strip())
    reference = quote or ""
    prefix = {"swap": "H-", "option": "Q-", "close": "CO-"}[product]
    positions = list(_IDS.finditer(reference))
    ids = tuple(dict.fromkeys(m[0].upper() for m in positions if m[0].startswith(prefix)))
    mapping: dict[str, str] = {}
    has_marker = False

    def fail(reason: str) -> Confirmation:
        return Confirmation(error=reason, mapping=dict(mapping), action=action)

    if not ids:
        return fail("missing_quote")
    if any(not m[0].startswith(prefix) for m in positions):
        return fail("ambiguous_quote")
    # Explicit sequence markers bind to the next order in that card/line, or a
    # preceding order on the same line (Java's '订单...（序号N）' footer).
    for marker in _SEQUENCE.finditer(reference):
        line_start = reference.rfind("\n", 0, marker.start()) + 1
        preceding = [m for m in positions if line_start <= m.start() < marker.start()]
        following = [m for m in positions if m.start() >= marker.end()]
        previous = preceding[-1] if preceding else None
        suffix = previous is not None and re.fullmatch(
            r"\s*[（(]\s*", reference[previous.end() : marker.start()]
        )
        after = following[0] if following else None
        # Java 平仓卡在序号和单号之间展示合约编号；只接受这一个明确的元数据行。
        contract_line = (
            rf"(?:合约编号\s*[:：]\s*{_CONTRACT.pattern}\s*)?" if product == "close" else ""
        )
        pair_prefix = after is not None and re.fullmatch(
            r"\s*" + contract_line + r"(?:(?:订单号|单号)\s*[:：]\s*|[:：]\s*)?",
            reference[marker.end() : after.start()],
        )
        target = previous if suffix else after if pair_prefix else None
        if target is None:
            line_end = reference.find("\n", marker.start())
            line = reference[line_start : line_end if line_end >= 0 else len(reference)]
            if re.search(r"请引用|例如|如只确认|如所有订单|如订单无误", line):
                continue
            mapping.clear()
            return fail("ambiguous_quote")
        has_marker = True
        if product == "swap" and not re.fullmatch(r"[1-9][0-9]*", marker[1]):
            mapping.clear()
            return fail("ambiguous_quote")
        number, oid = _number(marker[1]), target[0].upper()
        seq = str(number)
        if (
            number <= 0
            or (seq in mapping and mapping[seq] != oid)
            or (oid in mapping.values() and mapping.get(seq) != oid)
        ):
            mapping.clear()
            return fail("ambiguous_quote")
        mapping[seq] = oid
    if not mapping and not has_marker and (len(ids) == 1 or product != "swap"):
        mapping = {str(i): oid for i, oid in enumerate(ids, 1)}
    if confirmation_action(text) != action:
        return fail("format")
    remaining = text
    for alias in ALIASES[action]:
        remaining = remaining.replace(alias, "")
    selected_groups: list[set[str]] = []
    selection_order: list[str] = []
    raw_ids = [m[0].upper() for m in _IDS.finditer(remaining)]
    if raw_ids:
        if len(raw_ids) != len(set(raw_ids)) or not set(raw_ids).issubset(ids):
            return fail("unknown_order")
        selection_order = raw_ids
        selected_groups.append(set(raw_ids))
        remaining = _IDS.sub("", remaining)
    markers = list(_SEQUENCE.finditer(remaining))
    if (
        product == "swap"
        and action == "place"
        and not (raw_ids or markers)
        and text not in ALIASES[action]
    ):
        return fail("format")
    if markers:
        if (
            product == "swap"
            and action == "place"
            and not re.fullmatch(
                r"序号[1-9][0-9]*(?:、序号[1-9][0-9]*)*，(?:" + "|".join(ALIASES[action]) + r")",
                text,
            )
        ):
            return fail("format")
        if set(mapping.values()) != set(ids):
            mapping.clear()
            return fail("ambiguous_quote")
        seqs = [str(_number(m[1])) for m in markers]
        if len(seqs) != len(set(seqs)):
            return fail("duplicate_sequence")
        if any(seq not in mapping for seq in seqs):
            return fail("unknown_sequence")
        if not selection_order:
            selection_order = [mapping[seq] for seq in seqs]
        selected_groups.append({mapping[seq] for seq in seqs})
        remaining = _SEQUENCE.sub("", remaining)
    contracts = _CONTRACT.findall(remaining)
    if contracts:
        if product != "close" or len(contracts) != len(set(contracts)):
            return fail("unknown_contract")
        contract_ids: set[str] = set()
        for contract in contracts:
            targets = set()
            for match in _CONTRACT.finditer(reference):
                if match[0] != contract:
                    continue
                after = next((m for m in positions if m.start() >= match.end()), None)
                if after is not None and re.fullmatch(
                    r"\s*(?:订单号|单号)\s*[:：]\s*", reference[match.end() : after.start()]
                ):
                    targets.add(after[0].upper())
                    continue
                before = [m for m in positions if m.start() < match.start()]
                if before:
                    targets.add(before[-1][0].upper())
            if len(targets) != 1:
                return fail("unknown_contract")
            contract_ids.update(targets)
        selected_groups.append(contract_ids)
        remaining = _CONTRACT.sub("", remaining)
    remaining = _ALL.sub("", remaining)
    if not _SEPARATORS.fullmatch(remaining) and not (
        allow_parameters and only_execution_parameters(remaining, allow_choice=True)
    ):
        return fail("format")
    if selected_groups and any(group != selected_groups[0] for group in selected_groups[1:]):
        return fail("conflicting_selection")
    selected = selected_groups[0] if selected_groups else set(ids)
    return Confirmation(
        tuple(oid for oid in (selection_order or list(ids)) if oid in selected),
        mapping=mapping,
        action=action,
    )
