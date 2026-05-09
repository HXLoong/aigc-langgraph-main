"""Render 节点：根据 state 生成最终回复文本，供企微机器人发送。

本阶段先做简版：后续接入消息模板系统（SDK / Jinja2）。
"""
from __future__ import annotations

from typing import Any

from app.nodes.common import safe_node
from app.state import AgentState


@safe_node
async def render_reply(state: AgentState) -> dict[str, Any]:
    """生成 reply_text。"""

    # 若前面节点已设置 reply_text（如 completeness prompt），直接透传
    if state.get("reply_text") is not None:
        return {"trace": [{"node": "render_reply", "decision": "passthrough"}]}

    if state.get("error"):
        return {
            "reply_text": f"处理失败：{state['error']}\n\n如需帮助请点击反馈按钮。",
            "trace": [{"node": "render_reply", "decision": "error_path"}],
        }

    product_type = state.get("product_type")
    intent = state.get("intent")

    if product_type == "unknown":
        return {
            "reply_text": "未识别到有效指令，请明确指定产品（期权/互换）和操作（询价/下单/撤单等）。",
            "trace": [{"node": "render_reply", "decision": "unknown"}],
        }

    # 其他产品类型走各自子图的渲染
    api_result = state.get("api_result") or ""
    reply = api_result or "未识别到有效指令，请明确指定产品（期权/互换）和操作（询价/下单/撤单等）。"
    return {
        "reply_text": reply,
        "trace": [{"node": "render_reply", "decision": f"{product_type}_{intent}"}],
    }
