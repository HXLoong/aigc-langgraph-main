"""swap.confirm 节点 · 互换确认（confirm_order / confirm_cancel_order / confirm_modify_order 共用一个节点函数）。

DSL v2 把 Dify 的三个确认节点拆回独立提示词（互换-节点-确认下单 / 确认撤单 /
确认改单，字段规则彼此已有差异——确认下单要求提取 quote_content 中**所有**
订单号，确认撤单/确认改单只提取一个），本文件保留 ADR 0001 D5 的"合并成
1 个 Python 节点函数"架构决策（三者共用 orderId-only schema、只靠
intent 切换 prompt + expected_action），按 intent 动态加载对应 prompt 文件：

    confirm_order          → app/prompts/swap/confirm_order.md
    confirm_cancel_order   → app/prompts/swap/confirm_cancel.md
    confirm_modify_order   → app/prompts/swap/confirm_modify.md

互换-确认下单二次校验（DSL v2 if-else，仅 confirm_order 分支有）：
raw_content 必须包含"确认下单/确定下单/确认订单/下单确认"之一，否则不调用
LLM、不调后端，直接写 state['error']（由 render 走 CLAUDE.md 核心原则第 8 条
的 cascade 兜底文案，语义等价于 Dify false 分支的"存储消息意图"兜底应答）。
该检查只依赖 raw_content，与 LLM 输出无关，因此在本节点里前置执行，避免
校验失败时仍浪费一次 LLM 调用（Dify 原图是先调 LLM 再校验，行为对外一致，
仅节省成本）。

输入：raw_text + quote_content + intent
输出：state['confirm'] = {action, orderList}

action 取值：
- "place"  → confirm_order
- "cancel" → confirm_cancel_order
- "modify" → confirm_modify_order

LLM：thinking 模型 + with_structured_output（ADR 0010）。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ErrorInfo, TraceEntry
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.order_id import (
    extract_for_confirm_order,
    extract_for_confirm_single,
)

#: 互换-确认下单二次校验关键词（DSL v2 if-else `1781200000774`，含同义词）
_CONFIRM_ORDER_KEYWORDS: tuple[str, ...] = ("确认下单", "确定下单", "确认订单", "下单确认")


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
    _ACTION_INTENT = {
        "place": "confirm_order",
        "cancel": "confirm_cancel_order",
        "modify": "confirm_modify_order",
    }
    backend = await call_swap_backend(
        state,
        intent=_ACTION_INTENT.get(action, "confirm_order"),
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
