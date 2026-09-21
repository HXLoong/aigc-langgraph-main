"""互换确认节点。

确认下单遵循 CWAIJY-957：严格口令、必须引用、按明确序号映射选择订单。
协议不合法时返回确定性纠错，不调用交易接口，也不从记忆补单号。
确认撤单和确认改单同样必须引用当前订单并明确确认动作。
"""
from __future__ import annotations

from typing import Any

from app.extraction.identity import prepare_identity_scope
from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ExpectedAction, TraceEntry
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.confirmation import is_confirmation, parse_confirmation


def _expected_action(intent: str | None) -> ExpectedAction:
    """根据 intent 推 expected_action（合并版 3 子意图）。

    - confirm_order → "place"
    - confirm_cancel_order → "cancel"
    - confirm_modify_order → "modify"
    """
    if intent == "confirm_cancel_order":
        return "cancel"
    if intent == "confirm_modify_order":
        return "modify"
    return "place"  # confirm_order 或兜底


def confirm_order_secondary_check_passed(raw_text: str | None) -> bool:
    """兼容旧调用名，实际执行严格确认格式校验。"""
    return is_confirmation(raw_text)


@safe_node
async def swap_confirm(state: AgentState) -> dict[str, Any]:
    """按业务确认协议确定订单范围后提交。"""
    intent = state.get("intent")
    action = _expected_action(intent)

    raw, quote = state.get("raw_text"), state.get("quote_content")
    confirmation = parse_confirmation(raw, quote, action=action)
    if confirmation.error:
        return {
            "confirm": None, "reply_text": confirmation.correction(),
            "trace": [TraceEntry(node="swap_confirm", decision=f"confirmation:{confirmation.error}")],
        }
    order_ids: list[str | None] = list(confirmation.order_ids)
    identity_origin, identity_evidence, source = "quote", quote or "", "quote"
    prepared_state, order_ids, records = prepare_identity_scope(
        state, order_ids, scope="swap/confirm", origin=identity_origin, evidence=identity_evidence, selection=True,
    )
    confirmation.verify_scope(order_ids)
    order_list = [{"orderId": oid} for oid in order_ids]

    # action → SwapIntentionType 映射
    _action_intent = {
        "place": "confirm_order",
        "cancel": "confirm_cancel_order",
        "modify": "confirm_modify_order",
    }
    backend = await call_swap_backend(
        prepared_state,
        intent=_action_intent.get(action, "confirm_order"),
        order_list=order_list,
    )

    return {
        "field_records": records,
        "expected_action": action,
        "confirm": validated_confirm(action=action, orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_confirm",
                decision=f"deterministic,action={action},orders={len(order_list)},source={source}",
            )
        ],
    }


__all__ = ["swap_confirm", "confirm_order_secondary_check_passed"]
