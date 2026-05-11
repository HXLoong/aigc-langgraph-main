"""swap.hand_to_share 节点 · 互换订单手数→股数换算（Dify 原节点"互换-手转为股"）。

业务场景：
  swap.place_order 提取的 orderList 中，某些条目只有 placeOrderQuantityHand
  （手数）而无 placeOrderQuantity（股数）。本节点逐条调用 LLM，根据标的市场
  知识换算"每手股数"并填充 placeOrderQuantity。

调用方：swap_place_order 节点在参数提取后可选调用
  results = await convert_hands_to_shares_batch(order_dicts, llm=None)

Dify 原节点（node_id 1776947381378）处理逻辑：
  - 期货标的：Hand 和 Qty 原值透传，不换算
  - 非期货，只有股：原值透传
  - 非期货，有手数：placeOrderQuantity = placeOrderQuantityHand × 每手股数

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/hand_to_share.md（Dify 原文）。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.swap.models import SwapHandToShareItemOutput

logger = logging.getLogger(__name__)


async def convert_hands_to_shares_batch(
    order_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """逐条订单做手→股换算，返回更新后的 order_items 列表。

    - 无 placeOrderQuantityHand 的条目直接透传（跳过 LLM 调用）
    - LLM 调用失败时记录 warning 并原值透传（不让流程崩溃）

    Args:
        order_items: SwapOrderItem.model_dump() 列表

    Returns:
        更新后的 order_items 列表（新对象，不修改输入）
    """
    if not order_items:
        return []

    prompt = load_prompt("swap", "hand_to_share")
    llm = get_qwen_structured().with_structured_output(SwapHandToShareItemOutput)
    results: list[dict[str, Any]] = []

    for item in order_items:
        hand = item.get("placeOrderQuantityHand")
        if hand is None:
            results.append(dict(item))
            continue

        unique_id = str(uuid.uuid4())
        payload = {
            "uniqueId": unique_id,
            "placeOrderQuantity": item.get("placeOrderQuantity"),
            "placeOrderQuantityHand": hand,
            "placeOrderWindCode": item.get("placeOrderWindCode"),
        }

        try:
            out: SwapHandToShareItemOutput = await llm.ainvoke(
                [
                    ("system", prompt.system),
                    ("user", str(payload)),
                ]
            )
            updated = dict(item)
            updated["placeOrderQuantityHand"] = out.placeOrderQuantityHand
            updated["placeOrderQuantity"] = out.placeOrderQuantity
            results.append(updated)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hand_to_share 换算失败，原值透传: %s (windCode=%s)",
                exc,
                item.get("placeOrderWindCode"),
            )
            results.append(dict(item))

    return results


__all__ = ["convert_hands_to_shares_batch"]
