"""Code owns selection scope and candidate identity; models can only locate evidence."""
from __future__ import annotations

import re
from typing import Any, cast

from app.graph.state import AgentState
from app.subgraphs.swap.aggregate import (
    match_order_index,
    resolve_candidate_block,
    shortname_from_pick,
    windcode_from_pick,
)
from app.subgraphs.swap.models import (
    SwapCounterpartyPick,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
    SwapTickerPick,
)

_SCOPE = re.compile(r"H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|序号\s*[:：]?\s*(\d+)|第([一二三四五六七八九十\d]+)[笔单]")
_ALL = re.compile(r"(?:全部|所有|每一|各)(?:笔)?订单")
_VERBS = re.compile(r"^(?:请选择|选择|选用|选|换成|改成|更换为|换为|用)\s*[:：]?\s*")
_CP = re.compile(r"^(?:交易对手|对手|交易账号|账号|账户)\s*[:：]?\s*")
_TICKER = re.compile(r"^(?:标的|证券|股票)\s*[:：]?\s*")
_NUMERIC_PENDING = re.compile(r"(?:价格|数量|POV比例|可见委托量)[^\n。;；]{0,15}待补充|请补充参数[^】]*(?:价格|数量|POV|可见委托量)")


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = "零一二三四五六七八九"
    if text == "十":
        return 10
    if "十" in text:
        left, right = text.split("十", 1)
        return (digits.index(left) if left else 1) * 10 + (digits.index(right) if right else 0)
    return digits.index(text)


def order_sequences(state: AgentState) -> dict[str, int]:
    pairs = [(block.get("orderId"), block.get("orderSeq"))
             for block in state.get("quote_ticker_candidates") or []]
    pairs += [(match[2], int(match[1])) for match in re.finditer(
        r"序号\s*[:：]?\s*(\d+)[^\n;；]*?单号\s*[:：]?\s*(H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)",
        state.get("quote_content") or "",
    )]
    pairs += [(match[1], int(match[2])) for match in re.finditer(
        r"(H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*[（(]\s*序号\s*[:：]?\s*(\d+)\s*[）)]",
        state.get("quote_content") or "",
    )]
    result: dict[str, int] = {}
    for identity, sequence in pairs:
        if not isinstance(identity, str) or not isinstance(sequence, int):
            continue
        if identity in result and result[identity] != sequence:
            raise ValueError("引用订单序号不一致")
        result[identity] = sequence
    return result


def _segments(state: AgentState) -> list[tuple[list[int], str, str]]:
    raw = (state.get("raw_text") or "").strip()
    orders = (state.get("place_params") or {}).get("orderList") or []
    sequences = order_sequences(state)
    scopes = list(_SCOPE.finditer(raw))
    if not scopes:
        all_match = _ALL.search(raw)
        indices = list(range(len(orders))) if all_match else ([0] if len(orders) == 1 else [])
        body = raw[:all_match.start()] + raw[all_match.end():] if all_match else raw
        return [(indices, body.strip(), raw)]
    result: list[tuple[list[int], str, str]] = []
    if raw[:scopes[0].start()].strip(" ，,;；\n"):
        result.append(([], raw[:scopes[0].start()], raw[:scopes[0].start()]))
    for position, scope in enumerate(scopes):
        token = scope[0]
        if token.startswith("H-"):
            indices = [i for i, order in enumerate(orders) if order.get("orderId") == token]
        elif scope[1] is not None:
            indices = [i for i, order in enumerate(orders) if sequences.get(order.get("orderId")) == int(scope[1])]
        else:
            idx = _number(scope[2]) - 1
            indices = [idx] if 0 <= idx < len(orders) else []
        if len(indices) != 1:
            raise ValueError("选择指令的订单范围不存在或不唯一")
        end = scopes[position + 1].start() if position + 1 < len(scopes) else len(raw)
        body = raw[scope.end():end].strip(" ，,:：;；\n")
        evidence = raw[scope.start():end].strip(" ，,;；\n")
        result.append((indices, body, evidence))
    return result


def _literal(token: str, kind: str) -> tuple[str, bool]:
    noun = _CP if kind == "counterparty" else _TICKER
    explicit = bool(noun.search(token))
    previous = None
    while token != previous:
        explicit = explicit or bool(noun.search(token))
        previous = token
        token = _VERBS.sub("", noun.sub("", token)).strip()
    return token, explicit


def _cp_pick(token: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    literal, explicit = _literal(token, "counterparty")
    pick: dict[str, Any]
    if re.fullmatch(r"[A-Za-z]", literal):
        pick = {"letter": literal.upper()}
    elif explicit and (ordinal := re.fullmatch(r"第?([一二三四五六七八九十\d]+)个?", literal)):
        pick = {"ordinal": _number(ordinal[1])}
    elif literal and not literal.isdigit():
        pick = {"directName": literal}
    else:
        return None
    name = shortname_from_pick(pick, candidates)
    if name is None:
        if explicit or "letter" in pick:
            raise ValueError("交易对手选择不存在或不唯一")
        return None
    return {**pick, "directName": name}


def _ticker_pick(token: str, block: dict[str, Any], quote: str) -> dict[str, Any] | None:
    if _CP.search(token):
        return None
    literal, explicit = _literal(token, "ticker")
    explicit = explicit or bool(_TICKER.search(_VERBS.sub("", token)))
    pick: dict[str, Any]
    ordinal = re.fullmatch(r"第?([一二三四五六七八九十\d]+)(?:个(?:标的|候选)?)?", literal)
    if ordinal:
        if literal.isdigit() and token.strip() == literal and _NUMERIC_PENDING.search(quote):
            return None
        pick = {"seq": _number(ordinal[1])}
    elif literal:
        pick = {"directRef": literal}
    else:
        return None
    code = windcode_from_pick(pick, [block])
    if code is None:
        if explicit:
            raise ValueError("标的选择不存在或不唯一")
        return None
    matching = [candidate for candidate in block.get("candidates") or [] if candidate.get("code") == code]
    return {**pick, "directRef": code, "seq": pick.get("seq") or (matching[0].get("seq") if len(matching) == 1 else None)}


def _choices(state: AgentState, kind: str) -> list[dict[str, Any]] | None:
    orders = (state.get("place_params") or {}).get("orderList") or []
    if not orders:
        return []
    selected: dict[int, dict[str, Any]] = {}
    for indices, body, evidence in _segments(state):
        tokens = [token.strip() for token in re.split(r"[,，;；\n]", body) if token.strip()]
        for token in tokens:
            if kind == "counterparty":
                pick = _cp_pick(token, state.get("swap_counterparties") or [])
                picks = [(idx, pick) for idx in indices] if pick else []
                if pick and not indices:
                    raise ValueError("多订单选择必须明确订单范围")
            else:
                picks = []
                # Bare choices cannot be sprayed over all candidate blocks.
                possible = indices or list(range(len(orders)))
                for idx in possible:
                    identity = {"orderId": orders[idx].get("orderId")}
                    block = resolve_candidate_block(identity, state.get("quote_ticker_candidates") or [])
                    if block is None:
                        literal, explicit = _literal(token, "ticker")
                        ordinal = re.fullmatch(r"第?[一二三四五六七八九十\d]+(?:个(?:标的|候选)?)?", literal)
                        numeric_choice = ordinal and not _NUMERIC_PENDING.search(state.get("quote_content") or "")
                        full_code = re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z][A-Za-z0-9]*", literal)
                        if indices and (explicit or numeric_choice or full_code) and not _CP.search(token):
                            raise ValueError("指定订单没有可供选择的标的候选，已停止整批选择")
                        continue
                    pick = _ticker_pick(token, block, state.get("quote_content") or "")
                    if pick and not indices:
                        raise ValueError("多订单选择必须明确订单范围")
                    if pick:
                        picks.append((idx, pick))
            for idx, pick in picks:
                assert pick is not None
                value_key = "directName" if kind == "counterparty" else "directRef"
                if idx in selected and selected[idx][value_key] != pick[value_key]:
                    raise ValueError("同一订单存在互相冲突的选择")
                selected[idx] = {**pick, "idx": idx, "orderId": orders[idx].get("orderId"),
                                 "evidence": evidence, "confidence": 1.0}
    return list(selected.values()) or None


def counterparty_choice(state: AgentState) -> SwapSelectCounterpartyOutput | None:
    if not state.get("swap_counterparties"):
        return SwapSelectCounterpartyOutput()
    picks = _choices(state, "counterparty")
    if picks is None:
        return None
    return SwapSelectCounterpartyOutput(hasSignal=bool(picks), picks=[SwapCounterpartyPick.model_validate(pick) for pick in picks])


def ticker_choice(state: AgentState) -> SwapSelectTickerOutput | None:
    if not state.get("quote_ticker_candidates"):
        return SwapSelectTickerOutput()
    picks = _choices(state, "ticker")
    if picks is None:
        return None
    return SwapSelectTickerOutput(picks=[SwapTickerPick.model_validate(pick) for pick in picks])


def validate_picks(
    state: AgentState, picks: list[dict[str, Any]], kind: str,
) -> list[dict[str, Any]]:
    """An LLM may locate a span; Code must reconstruct the same scope and choice from it."""
    validated: dict[int, dict[str, Any]] = {}
    orders = (state.get("place_params") or {}).get("orderList") or []
    for pick in picks:
        evidence, confidence = pick.get("evidence"), pick.get("confidence")
        if not isinstance(evidence, str) or not evidence or evidence not in (state.get("raw_text") or ""):
            raise ValueError("选择指针缺少本轮原文证据")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValueError("选择指针缺少有效置信度")
        index = match_order_index(pick, orders, order_sequences(state), len(orders) == 1)
        if index < 0:
            raise ValueError("选择指针的订单标识不一致")
        reconstructed = _choices(cast(AgentState, {**state, "raw_text": evidence}), kind) or []
        value_key = "directName" if kind == "counterparty" else "directRef"
        name = shortname_from_pick(pick, state.get("swap_counterparties") or []) if kind == "counterparty" else windcode_from_pick(pick, state.get("quote_ticker_candidates") or [])
        matches = [choice for choice in reconstructed if choice["idx"] == index and choice[value_key] == name]
        if len(matches) != 1:
            raise ValueError("选择指针与原文证据或订单范围不一致")
        if index in validated and validated[index][value_key] != name:
            raise ValueError("同一订单存在互相冲突的选择")
        validated[index] = {**matches[0], "evidence": evidence, "confidence": confidence}
    return list(validated.values())
