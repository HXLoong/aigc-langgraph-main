"""remember_confirmed_params：一轮写类操作成功后，把订单号记进 ConversationMemory（ADR 0024 D4）。

写入条件（全部满足才覆盖既有记忆）：本轮无 error、`api_code == 0`、`expected_action` 属于
建单类（place / modify / inquiry / close）、能从业务对象或后端回复里拿到至少一个订单号。
撤单 / 确认类回合不改写记忆——裸"确认撤单"仍要读到上一轮建单的单号。

订单号来源：业务对象里的 orderId / confirmOrderNoList，其次后端回复文本按产品线正则提取
（swap `H-` / option `Q-` / option_close `CO-`）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.order_id import ORDER_ID_RE as CLOSE_ORDER_ID_RE
from app.subgraphs.option.order_id import ORDER_ID_RE as OPTION_ORDER_ID_RE
from app.subgraphs.swap.order_id import ORDER_ID_RE as SWAP_ORDER_ID_RE

#: 建单类动作：产生可被后续确认 / 撤单引用的订单
_REMEMBER_ACTIONS = frozenset({"place", "modify", "inquiry", "close"})
_ORDER_ID_RES: dict[str, re.Pattern[str]] = {
    "swap": SWAP_ORDER_ID_RE,
    "option": OPTION_ORDER_ID_RE,
    "option_close": CLOSE_ORDER_ID_RE,
}


def _ids_from_objects(state: AgentState) -> list[str]:
    ids: list[str] = []
    for key in ("place_params", "confirm", "cancel_params", "close_params"):
        obj = state.get(key)
        if not isinstance(obj, dict):
            continue
        for item in obj.get("orderList") or []:
            if isinstance(item, dict) and isinstance(item.get("orderId"), str) and item["orderId"]:
                ids.append(item["orderId"])
        for list_key in ("confirmOrderNoList", "closeOrderList"):
            for item in obj.get(list_key) or []:
                if isinstance(item, str) and item:
                    ids.append(item)
                elif isinstance(item, dict) and isinstance(item.get("orderId"), str) and item["orderId"]:
                    ids.append(item["orderId"])
    return ids


def _ids_from_api_result(state: AgentState, product_type: str) -> list[str]:
    pattern = _ORDER_ID_RES.get(product_type)
    result = state.get("api_result")
    if pattern is None or result is None:
        return []
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return [m.group(0).upper() if product_type == "option_close" else m.group(0) for m in pattern.finditer(text)]


@safe_node
async def remember_confirmed_params(state: AgentState) -> dict[str, Any]:
    product_type = state.get("product_type") or ""
    action = state.get("expected_action")
    if state.get("error") is not None or state.get("api_code") != 0 or action not in _REMEMBER_ACTIONS:
        return {"trace": [TraceEntry(node="remember_confirmed_params", decision="skip")]}
    order_ids = list(dict.fromkeys(_ids_from_objects(state) + _ids_from_api_result(state, product_type)))
    if not order_ids:
        return {"trace": [TraceEntry(node="remember_confirmed_params", decision="skip:no_order_ids")]}
    return {
        "last_confirmed_params": {
            "product_type": product_type,
            "intent": state.get("intent"),
            "expected_action": action,
            "order_ids": order_ids,
            "message_id": state.get("message_id"),
        },
        "trace": [
            TraceEntry(
                node="remember_confirmed_params",
                decision=f"remembered:{product_type}/{action},orders={len(order_ids)}",
            )
        ],
    }


__all__ = ["remember_confirmed_params"]
