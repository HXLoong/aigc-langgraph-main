"""swap.confirm 节点 · 互换确认（confirm_order / confirm_cancel_order / confirm_modify_order 共用一个节点函数）。

瘦身 P1（docs/swap-prompt-slimming-assessment.md 病灶 2）：原 LLM 调用的唯一任务
是提取 H- 订单号，改为 app/subgraphs/swap/order_id.py 确定性提取——零幻觉、
零成本、零延迟。三个子意图共用本节点函数（ADR 0001 D5 架构决策），只靠 intent
切换来源优先级（1:1 对照原三提示词）：

    confirm_order          → quote 全部（不遗漏），quote 无则 raw
    confirm_cancel_order   → quote 优先，否则 raw
    confirm_modify_order   → quote 优先，否则 raw

被替换的 3 个提示词文件已同批删除（另含旧合并版快照 confirm.md）。

互换-确认下单二次校验（DSL v2 if-else，仅 confirm_order 分支有）：
raw_content 必须包含"确认下单/确定下单/确认订单/下单确认"之一，否则不调后端，
直接写 state['error']（由 render 走 CLAUDE.md 核心原则第 8 条的 cascade 兜底
文案，语义等价于 Dify false 分支的"存储消息意图"兜底应答）。该检查只依赖
raw_content，因此在本节点里前置执行（Dify 原图是先调 LLM 再校验，行为对外
一致，仅节省成本）。

输入：raw_text + quote_content + intent
输出：state['confirm'] = {action, orderList}

action 取值：
- "place"  → confirm_order
- "cancel" → confirm_cancel_order
- "modify" → confirm_modify_order
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ErrorInfo, TraceEntry
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.intent import CONFIRM_ORDER_KEYWORDS
from app.subgraphs.swap.order_id import (
    extract_for_confirm_order,
    extract_for_confirm_single,
)

#: 互换-确认下单二次校验关键词（DSL v2 if-else `1781200000774`，含同义词）——与 intent 前置
#: 分流共用同一份词表（Dify 侧只有一份 has_confirmation_keyword），改词表只改 intent.py
_CONFIRM_ORDER_KEYWORDS: tuple[str, ...] = CONFIRM_ORDER_KEYWORDS


def _expected_action(intent: str | None) -> str:
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
    """互换-确认下单二次校验：raw_content 是否包含确认下单类关键词之一。

    纯函数（无副作用），供节点内前置短路判断，也可单独单测。
    """
    text = raw_text or ""
    return any(keyword in text for keyword in _CONFIRM_ORDER_KEYWORDS)


@safe_node
async def swap_confirm(state: AgentState) -> dict[str, Any]:
    """swap.confirm 节点（三子意图共用，按 intent 动态选 prompt）。"""
    intent = state.get("intent")
    action = _expected_action(intent)

    if intent == "confirm_order" and not confirm_order_secondary_check_passed(
        state.get("raw_text")
    ):
        return {
            "error": ErrorInfo(
                node="swap_confirm",
                type="ConfirmOrderSecondaryCheckFailed",
                message=(
                    "互换-确认下单二次校验未通过：raw_content 未包含"
                    "「确认下单/确定下单/确认订单/下单确认」任一关键词"
                ),
            ),
            "trace": [
                TraceEntry(
                    node="swap_confirm",
                    decision="confirm_order_secondary_check_failed",
                )
            ],
        }

    # 确定性订单号提取(瘦身 P1 去 LLM 化,来源优先级对照原三提示词):
    # confirm_order → quote 全部(不遗漏);confirm_cancel/modify → quote 优先单源
    raw, quote = state.get("raw_text"), state.get("quote_content")
    if action == "place":
        order_ids = extract_for_confirm_order(raw=raw, quote=quote)
    else:
        order_ids = extract_for_confirm_single(raw=raw, quote=quote)
    order_list = [{"orderId": oid} for oid in order_ids]

    # action → SwapIntentionType 映射
    _action_intent = {
        "place": "confirm_order",
        "cancel": "confirm_cancel_order",
        "modify": "confirm_modify_order",
    }
    backend = await call_swap_backend(
        state,
        intent=_action_intent.get(action, "confirm_order"),
        order_list=order_list,
    )

    return {
        "confirm": validated_confirm(action=action, orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_confirm",
                decision=f"deterministic,action={action},orders={len(order_list)}",
            )
        ],
    }


__all__ = ["swap_confirm", "confirm_order_secondary_check_passed"]
