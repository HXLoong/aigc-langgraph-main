"""close.place_close 链 · 合并输出（纯函数）。

Dify 原节点：`平仓参数提取-合并输出`（code）。
把 `reference_parser.parse_reference_message` 解析出的 successOrders 与
LLM 节点提取的 closeOrderList 合并为最终列表。

与 Dify 原版差异（工程适配）：
- Dify 原版要处理 closeOrderList 以字符串形式传入（含 markdown 代码块包裹）的
  情况，因为 Dify LLM 节点输出是纯文本。我们用 `with_structured_output` 直接拿到
  已解析的 Pydantic 对象列表，跳过字符串清洗/JSON.parse 这一段（行为等价，
  由 LangChain 结构化输出保证）。
"""
from __future__ import annotations

from typing import Any


def merge_close_orders(
    message_type: str,
    success_orders: list[dict[str, Any]] | None,
    llm_orders: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """合并 successOrders 与 llmOrders（1:1 移植合并语义）。

    - messageType != "close_result"（路径 A · 持仓列表）：直接用 LLM 输出
      （过滤掉既无 orderId 也无 internalTradeId 的空条目）。
    - messageType == "close_result"（路径 B · 平仓结果消息）：成功订单 + LLM
      提取的用户订单；同 orderId 时以 LLM 版本为准（LLM 含用户修改后的参数）。
    """
    llm_orders = list(llm_orders or [])
    success_orders = list(success_orders or [])

    if message_type != "close_result":
        return [o for o in llm_orders if o.get("internalTradeId") or o.get("orderId")]

    llm_order_ids = {o.get("orderId") for o in llm_orders}
    remaining_success_orders = [
        o for o in success_orders if o.get("orderId") not in llm_order_ids
    ]
    merged = [*remaining_success_orders, *llm_orders]
    return [o for o in merged if o.get("orderId") or o.get("internalTradeId")]


__all__ = ["merge_close_orders"]
