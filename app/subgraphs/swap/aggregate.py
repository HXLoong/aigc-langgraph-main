"""Candidate lookup helpers; explicit identities must agree and values stay in authority sets.

Selections map quote pointers or preserve explicit new expressions. The apply_picks node
checks evidence and order scope; Java performs security identification and validation.
"""
from __future__ import annotations

from typing import Any


def _as_int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def match_order_index(
    pick: dict[str, Any],
    order_list: list[dict[str, Any]],
    id_to_seq: dict[str, Any],
    single: bool,
) -> int:
    """All explicit identities must agree; a single order never overrides a foreign ID."""
    choices: list[set[int]] = []
    if pick.get("orderId") is not None:
        choices.append({i for i, order in enumerate(order_list) if order.get("orderId") == pick["orderId"]})
    if pick.get("orderSeq") is not None:
        seq = _as_int(pick["orderSeq"])
        choices.append({i for i, order in enumerate(order_list)
                        if seq is not None and id_to_seq.get(str(order.get("orderId") or "")) == seq})
    if pick.get("idx") is not None:
        idx = pick["idx"]
        choices.append({idx} if type(idx) is int and 0 <= idx < len(order_list) else set())
    if not choices:
        return 0 if single and len(order_list) == 1 else -1
    if any(len(choice) != 1 for choice in choices):
        return -1
    agreed = set.intersection(*choices)
    return next(iter(agreed)) if len(agreed) == 1 else -1


def resolve_candidate_block(
    pick: dict[str, Any], candidate_list: list[dict[str, Any]],
) -> dict[str, Any] | None:
    blocks = candidate_list
    explicit = False
    for key in ("orderId", "orderSeq"):
        if pick.get(key) is not None:
            explicit = True
            blocks = [block for block in blocks if block.get(key) == pick[key]]
    if not explicit and pick.get("idx") is not None:
        idx = pick["idx"]
        blocks = [blocks[idx]] if type(idx) is int and 0 <= idx < len(blocks) else []
    return blocks[0] if len(blocks) == 1 else None


def windcode_from_pick(
    pick: dict[str, Any], candidate_list: list[dict[str, Any]],
) -> str | None:
    """Resolve a quote pointer or preserve a new explicit expression for Java."""
    block = resolve_candidate_block(pick, candidate_list)
    if block is None:
        return None
    candidates = block.get("candidates") or []
    original_ref = str(pick.get("directRef") or "").strip()
    if pick.get("seq") is not None:
        candidates = [candidate for candidate in candidates if candidate.get("seq") == _as_int(pick["seq"])]
    if pick.get("directRef"):
        ref = str(pick["directRef"]).strip()
        exact = [candidate for candidate in candidates if str(candidate.get("code") or "").upper() == ref.upper()
                 or candidate.get("name") == ref]
        candidates = exact or [candidate for candidate in candidates
                               if ref and ref in (candidate.get("name") or "")]
    elif pick.get("seq") is None:
        return None
    codes = {candidate["code"] for candidate in candidates if candidate.get("code")}
    if not codes and original_ref and pick.get("seq") is None:
        return original_ref
    return next(iter(codes)) if len(codes) == 1 else None


def shortname_from_pick(pick: dict[str, Any], trs_list: list[dict[str, Any]]) -> str | None:
    """Every supplied pointer must resolve to the same unique authorized shortName."""
    choices: list[set[str]] = []
    if pick.get("directName"):
        name = str(pick["directName"]).strip()
        exact = {str(item["shortName"]) for item in trs_list if item.get("shortName") == name}
        choices.append(exact or {str(item["shortName"]) for item in trs_list
                                 if name and name in (item.get("shortName") or "")})
    if pick.get("letter") is not None:
        letter = str(pick["letter"]).upper()
        choices.append({str(item["shortName"]) for item in trs_list
                        if item.get("shortName") and str(item.get("sort") or "").upper() == letter})
    if pick.get("ordinal") is not None:
        ordinal = _as_int(pick["ordinal"])
        letter = chr(64 + ordinal) if ordinal is not None and 1 <= ordinal <= min(26, len(trs_list)) else ""
        choices.append({str(item["shortName"]) for item in trs_list
                        if letter and item.get("shortName") and str(item.get("sort") or "").upper() == letter})
    if not choices or any(len(choice) != 1 for choice in choices):
        return None
    agreed = set.intersection(*choices)
    return next(iter(agreed)) if len(agreed) == 1 else None


def unique_fresh_counterparty(
    fresh_res: dict[str, Any], trs_list: list[dict[str, Any]], raw_content: str,
) -> tuple[str | None, str]:
    """移植 Dify 1780652971845 的名称/证据校验，附带原因供 trace 使用。

    输入已经过结构化模型校验，无需 Dify 的 JSON 字符串解码适配。
    不在代码中增加简称匹配、纯数字过滤或账户 ID 去重规则。
    """
    has_signal = fresh_res.get("hasSignal")
    if has_signal is not True and not (
        isinstance(has_signal, str) and has_signal.strip().lower() == "true"
    ):
        return None, "no_signal"
    matches = fresh_res.get("matches")
    if not isinstance(matches, list) or not matches:
        return None, "no_matches"
    allowed = {
        str(t.get("shortName") or "").strip() for t in trs_list if isinstance(t, dict)
    }
    allowed.discard("")
    raw = str(raw_content or "")
    names = set()
    for item in matches:
        if not isinstance(item, dict):
            return None, "invalid_match"
        shortname = str(item.get("shortName") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not shortname or shortname not in allowed:
            return None, "name_outside_candidates"
        if not evidence or evidence not in raw:
            return None, "invalid_evidence"
        names.add(shortname)
    if len(names) != 1:
        return None, "ambiguous_names"
    return next(iter(names)), "unique_name"


def apply_fresh_counterparty(order_list: list[dict[str, Any]], shortname: str | None) -> str:
    """Dify 整批补全：先检查所有原值；任一冲突即整批保持原样。"""
    if not shortname:
        return "no_shortname"
    existing = set()
    for order in order_list:
        if not isinstance(order, dict):
            return "invalid_order"
        value = str(order.get("placeOrderShortname") or "").strip()
        if value:
            existing.add(value)
    if existing - {shortname}:
        return "existing_counterparty_conflict"
    for order in order_list:
        order["placeOrderShortname"] = shortname
    return "applied"


__all__ = [
    "match_order_index",
    "resolve_candidate_block",
    "windcode_from_pick",
    "shortname_from_pick",
    "unique_fresh_counterparty",
    "apply_fresh_counterparty",
]
