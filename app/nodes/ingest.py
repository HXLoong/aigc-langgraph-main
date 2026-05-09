"""Ingest 节点：规整企微输入，加载会话级上下文。

对应 Dify 中的：获取机器人名称列表 + 处理历史输入 + 互换参数聚合
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.nodes.common import safe_node
from app.state import AgentState
from app.tools.otc_backend import OtcBackendClient

logger = logging.getLogger(__name__)


@safe_node
async def ingest(state: AgentState) -> dict[str, Any]:
    """
    并行加载：
    - 机器人名称列表（过滤 @xxx 片段）
    - 本会话已下单的历史列表（互换场景用于参数补充）
    - 交易对手列表（互换/平仓场景）
    - 历史对话消息（从 checkpoint 读，在 api/routes.py 层已预加载）

    历史消息由上层（FastAPI 路由）通过 state['history_messages'] 预先注入，
    因为这里没有 graph 对象的引用；所以此节点只做 API 拉取。
    """
    async with OtcBackendClient() as client:
        # 并行 3 个请求，显著降低 ingest 延迟
        bot_task = client.bot_name_list()
        wx = state["wechat_input"]
        orders_task = client.conversation_orders(
            conversation_id=wx.get("conversation_id", ""),
            user_id=wx.get("user_id", ""),
            room_id=wx.get("room_id", ""),
        )
        cp_task = client.counterparty_list()

        bot_names, conv_orders, counterparties = await asyncio.gather(
            bot_task, orders_task, cp_task,
            return_exceptions=True,
        )

    # 异常降级为空值
    bot_names = bot_names if isinstance(bot_names, list) else []
    conv_orders = conv_orders if isinstance(conv_orders, list) else []
    counterparties = counterparties if isinstance(counterparties, list) else []

    return {
        "bot_name_list": bot_names,
        "conversation_orders": conv_orders,
        "counterparty_list": counterparties,
        "history_messages": [*state.get("history_messages", []), {
            "role": "user",
            "content": wx.get("raw_content", ""),
            "quote_content": wx.get("quote_content", "") or "",
        }],
        "trace": [{
            "node": "ingest",
            "output_preview": (
                f"bots={len(bot_names)} orders={len(conv_orders)} "
                f"cps={len(counterparties)}"
            ),
        }],
    }
