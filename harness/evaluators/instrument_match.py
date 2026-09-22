"""Langfuse Code Evaluator：标的识别——逐轮比对 LLM 提取的标的原文与交易品种。

LangGraph 只提取用户原文里的标的表达（`placeOrderWindCode` 逐字保留）和交易品种，
权威识别由 Java 完成（docs/backend-instrument-boundary.md）。因此本评估器只评"送给后端的
表达对不对"：expected.instruments[i].expression 是可接受表达的任一候选列表，
transaction_type 是可接受枚举的任一候选；按订单无序多重集匹配，缺单、多单、品种不符都算失败。
上传到 Langfuse 后独立执行，不 import harness 其它模块。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Score:
    name: str
    value: int | float | str | bool
    data_type: str
    comment: str | None = None
    config_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class EvaluationResult:
    scores: list[Score]


_WS = re.compile(r"[\s　]+")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _candidates(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _normalize(text: str) -> str:
    return _WS.sub("", text).lower()


def _first(value: Any, *keys: str) -> Any:
    if not isinstance(value, dict):
        return None
    for key in keys:
        if value.get(key) is not None:
            return value[key]
    return None


def _actual_orders(turn: Any) -> list[dict[str, str]]:
    """turn.place_params.orderList[*] → [{code, market}]，兼容 alias 与 snake_case。"""
    params = _first(turn, "place_params") if isinstance(turn, dict) else None
    orders = _first(params, "orderList", "order_list") if isinstance(params, dict) else None
    result: list[dict[str, str]] = []
    for order in orders if isinstance(orders, list) else []:
        code = _first(order, "placeOrderWindCode", "place_order_wind_code")
        market = _first(order, "placeOrderTransactionType", "place_order_transaction_type")
        if code is None:
            continue
        result.append({"code": str(code), "market": "" if market is None else str(market)})
    return result


def _expected_instruments(turn: Any) -> list[dict[str, Any]]:
    expected = turn.get("expected") if isinstance(turn, dict) else None
    instruments = expected.get("instruments") if isinstance(expected, dict) else None
    return [item for item in instruments if isinstance(item, dict)] if isinstance(instruments, list) else []


def evaluate(ctx: Any) -> EvaluationResult:
    """对 Experiment Item 的每轮 orderList 生成一个 Boolean Score。"""
    experiment = getattr(ctx, "experiment", None)
    expected_output = _json_object(
        getattr(experiment, "item_expected_output", None) if experiment else None
    )
    output = _json_object(getattr(ctx.observation, "output", None))

    expected_turns: list[Any] = [expected_output]
    sub_scenes = expected_output.get("sub_scenes")
    if isinstance(sub_scenes, list):
        expected_turns.extend(sub_scenes)

    actual_turns = output.get("turns")
    if not isinstance(actual_turns, list):
        actual_turns = [output]

    mismatches: list[str] = []
    assertion_count = 0
    for index, expected_turn in enumerate(expected_turns):
        wanted = _expected_instruments(expected_turn)
        if not wanted:
            continue
        assertion_count += len(wanted)
        turn_no = index + 1
        if index >= len(actual_turns):
            mismatches.append(f"第 {turn_no} 轮无实际输出（早停或未执行），期望 {len(wanted)} 个标的")
            continue
        remaining = _actual_orders(actual_turns[index])
        all_codes = "、".join(order["code"] for order in remaining) or "(空)"
        missing = False
        for item in wanted:
            expressions = _candidates(item.get("expression"))
            label = expressions[0] if expressions else "(未标注表达)"
            normalized = {_normalize(text) for text in expressions}
            matched = next(
                (order for order in remaining if _normalize(order["code"]) in normalized), None
            )
            if matched is None:
                missing = True
                mismatches.append(f"第 {turn_no} 轮未提取到标的：{label}（实际 {all_codes}）")
                continue
            remaining.remove(matched)
            markets = _candidates(item.get("transaction_type"))
            if markets and matched["market"] not in markets:
                mismatches.append(
                    f"第 {turn_no} 轮 {label} 交易品种不符：期望 {'/'.join(markets)}，"
                    f"实际 {matched['market'] or '(空)'}"
                )
        # 已报漏提取时，剩余订单多半是同一单的错误表达，不再重复计为"多出"
        if remaining and not missing:
            extra = "、".join(order["code"] for order in remaining)
            mismatches.append(f"第 {turn_no} 轮多出标的：{extra}")

    if assertion_count == 0:
        return EvaluationResult(
            scores=[
                Score(
                    name="det_instrument_match_pass",
                    value=False,
                    data_type="BOOLEAN",
                    comment="没有可比对的 expected.instruments；标的识别用例必须逐轮标注",
                    metadata={"assertion_count": 0, "mismatch_count": 0},
                )
            ]
        )

    passed = not mismatches
    return EvaluationResult(
        scores=[
            Score(
                name="det_instrument_match_pass",
                value=passed,
                data_type="BOOLEAN",
                comment="全部轮次标的表达与交易品种均匹配" if passed else "；".join(mismatches),
                metadata={
                    "assertion_count": assertion_count,
                    "mismatch_count": len(mismatches),
                },
            )
        ]
    )
