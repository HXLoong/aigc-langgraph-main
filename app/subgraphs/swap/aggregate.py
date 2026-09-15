"""swap.aggregate_ticker_counterparty · 互换-标的对手覆盖聚合（Dify code 节点 1:1 移植）。

纯数据聚合，无业务规则：把 LLM-C（互换-节点-下单）抽好的 orderList，用
LLM-A（互换-选择标的）、LLM-B（互换-选择交易对手）的指针结果确定性查表覆盖
placeOrderWindCode / placeOrderShortname 两个字段，其余字段原样保留。

- 标的覆盖：候选语境(candidate_list 非空)时用 LLM-A 指针覆盖；解析到非空才覆盖，
  否则保留原值（非破坏性，绝不置 None）。
- 对手覆盖：LLM-B 有信号(hasSignal)时用指针覆盖；解析到非空才覆盖，否则保留原值。

1:1 对照 `/private/tmp/.../spec/code_nodes/互换-标的对手覆盖聚合.py`
（本模块把该 code 节点拆成 `apply_underlying` / `apply_counterparty` 两个独立
纯函数，分别供 swap.select_ticker / swap.select_counterparty 两个节点调用——
两个 apply_* 互不依赖，拆开调用与 Dify 原节点一次性调用两者语义等价）。
"""
from __future__ import annotations

from typing import Any


def _as_int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def build_id_to_seq(candidate_list: list[dict[str, Any]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for blk in candidate_list:
        if blk.get("orderId") is not None:
            mapping[blk["orderId"]] = blk.get("orderSeq")
    return mapping


def match_order_index(
    pick: dict[str, Any],
    order_list: list[dict[str, Any]],
    id_to_seq: dict[str, Any],
    single: bool,
) -> int:
    """pick 落到 order_list 哪个下标：orderId > orderSeq(反查) > idx；单订单=0；对不上=-1。"""
    if single:
        return 0
    order_id = pick.get("orderId")
    if order_id is not None:
        for i, o in enumerate(order_list):
            if o.get("orderId") == order_id:
                return i
    order_seq = _as_int(pick.get("orderSeq"))
    if order_seq is not None:
        for i, o in enumerate(order_list):
            if o.get("orderId") is not None and id_to_seq.get(o.get("orderId")) == order_seq:
                return i
    idx = pick.get("idx")
    if isinstance(idx, int) and 0 <= idx < len(order_list):
        return idx
    return -1


def resolve_candidate_block(
    pick: dict[str, Any], candidate_list: list[dict[str, Any]]
) -> dict[str, Any] | None:
    order_id = pick.get("orderId")
    order_seq = _as_int(pick.get("orderSeq"))
    idx = pick.get("idx")
    for blk in candidate_list:
        if order_id is not None and blk.get("orderId") == order_id:
            return blk
    for blk in candidate_list:
        if order_seq is not None and blk.get("orderSeq") == order_seq:
            return blk
    if isinstance(idx, int) and 0 <= idx < len(candidate_list):
        return candidate_list[idx]
    if len(candidate_list) == 1:
        return candidate_list[0]
    return None


def windcode_from_pick(
    pick: dict[str, Any], candidate_list: list[dict[str, Any]]
) -> str | None:
    """LLM-A 指针→真实 windCode：seq→candidates.code；directRef→匹配候选 canonical，匹配不到原样。"""
    blk = resolve_candidate_block(pick, candidate_list)
    seq = _as_int(pick.get("seq"))
    if seq is not None and blk:
        for ca in blk.get("candidates", []):
            if ca.get("seq") == seq:
                return ca.get("code")
        return None
    ref = pick.get("directRef")
    if ref:
        ref = str(ref).strip()
        if blk:
            for ca in blk.get("candidates", []):
                name = ca.get("name") or ""
                if ca.get("code") == ref or name == ref or (name and (ref in name or name in ref)):
                    return ca.get("code")
        return ref
    return None


def shortname_from_pick(pick: dict[str, Any], trs_list: list[dict[str, Any]]) -> str | None:
    """LLM-B 指针→真实 shortName：directName 按名匹配；letter/ordinal→sort→shortName；查不到 None。"""
    name = pick.get("directName")
    if name:
        name = str(name).strip()
        for t in trs_list:
            if t.get("shortName") == name:
                return t.get("shortName")
        for t in trs_list:
            sn = t.get("shortName") or ""
            if sn and (name in sn or sn in name):
                return t.get("shortName")
        return None
    sort = None
    if pick.get("letter") is not None:
        sort = str(pick["letter"]).upper()
    elif pick.get("ordinal") is not None:
        x = _as_int(pick.get("ordinal"))
        if x is not None and 1 <= x <= len(trs_list):
            sort = chr(64 + x)
        else:
            return None
    if sort is None:
        return None
    for t in trs_list:
        if str(t.get("sort")).upper() == sort:
            return t.get("shortName")
    return None


def apply_underlying(
    order_list: list[dict[str, Any]],
    a_picks: list[dict[str, Any]],
    candidate_list: list[dict[str, Any]],
) -> None:
    """标的覆盖(非破坏)：LLM-A 解析到非空 windCode 才覆盖该订单；解析为空/未选中 → 保留原值，绝不置 None。

    就地修改 order_list（与 Dify code 节点行为一致）。candidate_list 为空时直接跳过。
    """
    if not candidate_list:
        return
    single = len(order_list) == 1
    id_to_seq = build_id_to_seq(candidate_list)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for p in a_picks:
        i = match_order_index(p, order_list, id_to_seq, single)
        if i >= 0:
            grouped.setdefault(i, []).append(p)
    for i, picks in grouped.items():
        code = None
        for p in picks:
            v = windcode_from_pick(p, candidate_list)
            if v is not None:
                code = v
                break
        if code is not None:
            order_list[i]["placeOrderWindCode"] = code


def apply_counterparty(
    order_list: list[dict[str, Any]],
    b_has_signal: bool,
    b_picks: list[dict[str, Any]],
    trs_list: list[dict[str, Any]],
) -> None:
    """对手覆盖(非破坏)：LLM-B 解析到非空 shortName 才覆盖该订单；无信号/解析空 → 保留原值，不清空。

    就地修改 order_list（与 Dify code 节点行为一致）。
    """
    if not b_has_signal or not order_list:
        return
    single = len(order_list) == 1
    id_to_seq = build_id_to_seq([])  # 对手覆盖不依赖候选标的块，仅靠 orderId/idx
    grouped: dict[int, list[dict[str, Any]]] = {}
    for p in b_picks:
        i = 0 if single else match_order_index(p, order_list, id_to_seq, single)
        if i >= 0:
            grouped.setdefault(i, []).append(p)
    for i, picks in grouped.items():
        sn = None
        for p in picks:
            v = shortname_from_pick(p, trs_list)
            if v is not None:
                sn = v
                break
        if sn is not None:
            order_list[i]["placeOrderShortname"] = sn


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
    "build_id_to_seq",
    "match_order_index",
    "resolve_candidate_block",
    "windcode_from_pick",
    "shortname_from_pick",
    "apply_underlying",
    "apply_counterparty",
    "unique_fresh_counterparty",
    "apply_fresh_counterparty",
]
