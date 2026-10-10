"""意图集本地确定性评分：迁自平台 JS 规则，评分不再依赖 Langfuse。

- intent_match：逐轮比对 expected.product_type / intent / entry_branch。
- instrument_match：逐轮比对 expected.instruments（标的原文表达与交易品种）。

只比对 expected 明确标注的键；一轮都未标注判失败，避免标注缺失被当成通过。
"""
from __future__ import annotations

import json
from typing import Any

from harness.golden import GoldenCase
from harness.multi_turn import MultiTurnResult

_INTENT_KEYS = ("product_type", "intent", "entry_branch")


def _as_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize(text: Any) -> str:
    """忽略全部空白（含全角空格）并统一小写，与平台 JS 口径一致。"""
    return "".join(str(text).split()).lower()


def _candidates(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    return []


def _first(source: Any, *keys: str) -> Any:
    obj = _as_object(source)
    for key in keys:
        if obj.get(key) is not None:
            return obj.get(key)
    return None


def _actual_value(turn: Any, key: str) -> str:
    if key == "product_type":
        value = getattr(turn, "product_type", None)
    elif key == "intent":
        value = getattr(turn, "intent", None)
    else:
        value = turn.outputs.get(key)
    return "" if value is None else str(value)


def intent_match(case: GoldenCase, result: MultiTurnResult) -> dict[str, Any]:
    mismatches: list[str] = []
    assertions = 0
    for index, turn in enumerate(case.turns):
        expected = _as_object(turn.expected)
        wanted: dict[str, str] = {}
        for key in _INTENT_KEYS:
            value = expected.get(key)
            if isinstance(value, str) and value.strip():
                wanted[key] = value.strip()
        if not wanted:
            continue
        assertions += len(wanted)
        turn_no = index + 1
        if index >= len(result.turns):
            mismatches.append(
                f"第 {turn_no} 轮无实际输出（早停或未执行），期望 {json.dumps(wanted, ensure_ascii=False)}"
            )
            continue
        for key, expected_value in wanted.items():
            actual_value = _actual_value(result.turns[index], key)
            if actual_value != expected_value:
                mismatches.append(
                    f"第 {turn_no} 轮 {key} 不符：期望 {expected_value}，实际 {actual_value or '(空)'}"
                )
    no_assertions = assertions == 0
    passed = not no_assertions and not mismatches
    return {
        "name": "det_intent_match_pass",
        "value": passed,
        "comment": (
            "没有可比对的 expected.product_type / intent / entry_branch；意图集用例必须逐轮标注"
            if no_assertions
            else ("全部轮次产品、意图及已标注入口均匹配" if passed else "；".join(mismatches))
        ),
        "metadata": {"assertion_count": assertions, "mismatch_count": len(mismatches)},
    }


def _actual_orders(turn: Any) -> list[dict[str, str]]:
    orders = _first(turn.place_params, "orderList", "order_list")
    if not isinstance(orders, list):
        return []
    result: list[dict[str, str]] = []
    for order in orders:
        code = _first(order, "placeOrderWindCode", "place_order_wind_code")
        if code is None:
            continue
        market = _first(order, "placeOrderTransactionType", "place_order_transaction_type")
        result.append({"code": str(code), "market": "" if market is None else str(market)})
    return result


def instrument_match(case: GoldenCase, result: MultiTurnResult) -> dict[str, Any]:
    mismatches: list[str] = []
    assertions = 0
    for index, turn in enumerate(case.turns):
        expected = _as_object(turn.expected)
        instruments = expected.get("instruments")
        wanted = (
            [item for item in instruments if isinstance(item, dict)]
            if isinstance(instruments, list)
            else []
        )
        if not wanted:
            continue
        assertions += len(wanted)
        turn_no = index + 1
        if index >= len(result.turns):
            mismatches.append(f"第 {turn_no} 轮无实际输出（早停或未执行），期望 {len(wanted)} 个标的")
            continue

        remaining = _actual_orders(result.turns[index])
        all_codes = "、".join(order["code"] for order in remaining) or "(空)"
        missing = False
        for instrument in wanted:
            expressions = _candidates(instrument.get("expression"))
            label = expressions[0] if expressions else "(未标注表达)"
            accepted = {_normalize(expression) for expression in expressions}
            matched_at = next(
                (i for i, order in enumerate(remaining) if _normalize(order["code"]) in accepted),
                -1,
            )
            if matched_at < 0:
                missing = True
                mismatches.append(f"第 {turn_no} 轮未提取到标的：{label}（实际 {all_codes}）")
                continue
            matched = remaining.pop(matched_at)
            markets = _candidates(instrument.get("transaction_type"))
            if markets and matched["market"] not in markets:
                mismatches.append(
                    f"第 {turn_no} 轮 {label} 交易品种不符：期望 {'/'.join(markets)}，"
                    f"实际 {matched['market'] or '(空)'}"
                )
        if remaining and not missing:
            mismatches.append(f"第 {turn_no} 轮多出标的：{'、'.join(order['code'] for order in remaining)}")
    no_assertions = assertions == 0
    passed = not no_assertions and not mismatches
    return {
        "name": "det_instrument_match_pass",
        "value": passed,
        "comment": (
            "没有可比对的 expected.instruments；标的识别用例必须逐轮标注"
            if no_assertions
            else ("全部轮次标的表达与交易品种均匹配" if passed else "；".join(mismatches))
        ),
        "metadata": {"assertion_count": assertions, "mismatch_count": len(mismatches)},
    }


def score_intent(case: GoldenCase, result: MultiTurnResult) -> dict[str, Any]:
    """意图套件两条确定性评分合并为整体判定。"""
    scores = [intent_match(case, result), instrument_match(case, result)]
    scored = [score for score in scores if score["metadata"]["assertion_count"] > 0]
    passed = bool(scored) and all(score["value"] for score in scored)
    return {"scores": scores, "passed": passed}
