"""Code owns selection scope and candidate identity; models can only locate evidence."""
from __future__ import annotations

import re
from typing import Any, cast

from app.extraction.fields import FieldRecord
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
_QUOTE_ID = re.compile(r"H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_QUOTE_HEADER = re.compile(r"(?:单号|订单号|订单)\s*[:：]?\s*(H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)")
_CP_PENDING = re.compile(
    r"(?:交易对手|对手|交易账[号户]|账[号户])\s*[:：]?\s*[【\[]?\s*待补充"
    r"|请补充参数[^】\]\n]*(?:交易对手|对手|交易账[号户]|账[号户])"
)


def _reference_blocks(state: AgentState) -> list[tuple[str, str]]:
    """按引用原文顺序读取订单块，不用本次提交或候选数组重排。"""
    quote = state.get("quote_content") or ""
    headers = list(_QUOTE_HEADER.finditer(quote))
    positions = [(match.start(), match[1]) for match in headers] if headers else [
        (match.start(), match[0]) for match in _QUOTE_ID.finditer(quote)
    ]
    blocks: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, (start, identity) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(quote)
        if identity not in seen:
            seen.add(identity)
            blocks.append((identity, quote[start:end]))
    return blocks


def _pending_counterparty_indices(state: AgentState) -> list[int]:
    """无范围选择只广播到引用中对手待补充的订单，目标遗漏则整批拒绝。"""
    orders = (state.get("place_params") or {}).get("orderList") or []
    indices: list[int] = []
    for identity, block in _reference_blocks(state):
        if not _CP_PENDING.search(block):
            continue
        matches = [index for index, order in enumerate(orders) if order.get("orderId") == identity]
        if len(matches) != 1:
            raise ValueError("交易对手待补充订单未完整提交或身份不唯一")
        indices.append(matches[0])
    return indices


def _number(text: str) -> int:
    """读取用户指定的序号，数字转换只用于结构选择，不计算交易数量。"""
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
    """从当前引用建立订单号与显示序号的唯一映射。"""
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
    pairs += [(match[2], int(match[1])) for match in re.finditer(
        r"序号\s*[:：]?\s*(\d+)\s*(?:单号|订单号)\s*[:：]?\s*(H-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)",
        state.get("quote_content") or "",
    )]
    result: dict[str, int] = {}
    for identity, sequence in pairs:
        if not isinstance(identity, str) or not isinstance(sequence, int):
            continue
        if identity in result and result[identity] != sequence:
            raise ValueError("引用订单序号不一致")
        if any(other != identity and value == sequence for other, value in result.items()):
            raise ValueError("引用订单序号指向多个订单")
        result[identity] = sequence
    return result


def _segments(state: AgentState) -> list[tuple[list[int], str, str]]:
    """按当前明确订单定位切分选择语句，范围不唯一时拒绝。"""
    raw = (state.get("raw_text") or "").strip()
    orders = (state.get("place_params") or {}).get("orderList") or []
    sequences = order_sequences(state)
    referenced = [identity for identity, _ in _reference_blocks(state)]
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
            ordinal = _number(scope[2]) - 1
            identity = referenced[ordinal] if 0 <= ordinal < len(referenced) else None
            indices = [i for i, order in enumerate(orders) if identity is not None and order.get("orderId") == identity]
        if len(indices) != 1:
            raise ValueError("选择指令的订单范围不存在或不唯一")
        end = scopes[position + 1].start() if position + 1 < len(scopes) else len(raw)
        body = raw[scope.end():end].strip(" ，,:：;；\n")
        evidence = raw[scope.start():end].strip(" ，,;；\n")
        result.append((indices, body, evidence))
    return result


def _literal(token: str, kind: str) -> tuple[str, bool]:
    """去掉选择动作词，保留候选名称或编号的原文。"""
    noun = _CP if kind == "counterparty" else _TICKER
    explicit = bool(noun.search(token))
    previous = None
    while token != previous:
        explicit = explicit or bool(noun.search(token))
        previous = token
        token = _VERBS.sub("", noun.sub("", token)).strip()
    return token, explicit


def _cp_pick(token: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """在给定授权对手列表中解析明确字母、序号或唯一名称。"""
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
    """只在当前订单的引用候选中解析选择，原始代码交 Java 识别。"""
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
        if (not explicit and re.fullmatch(r"[A-Za-z]", literal)) or re.fullmatch(
            r"(?:市价|限价|价格|数量|金额|跟量|POV|TWAP|VWAP|ICEBERG|SNIPER).*"
            r"|[0-9.,]+\s*(?:股|手|万|亿|元|%|分钟|小时)", literal, re.I,
        ):
            return None
        named = any(literal.casefold() in str(c.get("name") or "").casefold()
                    or literal.casefold() == str(c.get("code") or "").casefold()
                    for c in block.get("candidates") or [])
        if not (explicit or _VERBS.match(token) or named or re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z]+", literal)):
            return None
        pick = {"directRef": literal}
    else:
        return None
    code = windcode_from_pick(pick, [block])
    if code is None:
        return None
    matching = [candidate for candidate in block.get("candidates") or [] if candidate.get("code") == code]
    return {**pick, "directRef": code, "seq": pick.get("seq") or (matching[0].get("seq") if len(matching) == 1 else None)}


def _choices(state: AgentState, kind: str) -> list[dict[str, Any]] | None:
    """按本次订单范围组合候选选择，拒绝冲突和缺失目标。"""
    orders = (state.get("place_params") or {}).get("orderList") or []
    if not orders:
        return []
    selected: dict[int, dict[str, Any]] = {}
    for indices, body, evidence in _segments(state):
        tokens = [token.strip() for token in re.split(r"[,，;；\n]", body) if token.strip()]
        for token in tokens:
            if kind == "counterparty":
                pick = _cp_pick(token, state.get("swap_counterparties") or [])
                targets = indices
                # 单独字母/名称按 Dify 填充所有待补对手；已完整订单不自动改写。
                if pick and not _SCOPE.search(evidence) and not _ALL.search(evidence):
                    pending = _pending_counterparty_indices(state)
                    if pending:
                        targets = pending
                picks = [(idx, pick) for idx in targets] if pick else []
                if pick and not targets:
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
    """对明确的对手选择使用代码定位，不额外请求模型。"""
    if not state.get("swap_counterparties"):
        return SwapSelectCounterpartyOutput()
    picks = _choices(state, "counterparty")
    if picks is None:
        return None
    return SwapSelectCounterpartyOutput(has_signal=bool(picks), picks=[SwapCounterpartyPick.model_validate(pick) for pick in picks])


def ticker_choice(state: AgentState) -> SwapSelectTickerOutput | None:
    """对明确的标的选择使用代码定位，不调用证券查询。"""
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


def validate_applied_picks(state: AgentState) -> None:
    """清洗与提交边界重验选择账本，不能用伪造的派生路径绕过选择校验。"""
    records = state.get("field_records") or {}
    for path, record in records.items():
        match = re.fullmatch(r"swap/place_order\.orderList\.(\d+)\.(placeOrderWindCode|placeOrderShortname)", path)
        if not match or not isinstance(record, FieldRecord):
            continue
        selection_path = path + ".selection"
        if selection_path not in record.derived_from:
            continue
        selection = records.get(selection_path)
        if not isinstance(selection, FieldRecord) or not selection.locked or not isinstance(selection.value, dict):
            raise ValueError("候选选择账本缺少有效原文指针")
        if selection.evidence != selection.value.get("evidence"):
            raise ValueError("候选选择证据与账本不一致")
        kind = "ticker" if match[2] == "placeOrderWindCode" else "counterparty"
        picks = validate_picks(state, [selection.value], kind)
        value_key = "directRef" if kind == "ticker" else "directName"
        if len(picks) != 1 or picks[0]["idx"] != int(match[1]) or picks[0][value_key] != record.value:
            raise ValueError("候选选择结果与有效字段锁不一致")
