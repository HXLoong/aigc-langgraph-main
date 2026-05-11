"""render 节点：从 final state 渲染回复给 API 层。

M1 阶段：占位（API 层直接从 final state 构造 Dify Workflow Run API outputs）。
M2 阶段：在此处接入业务回复 LLM 生成（按 intent + 业务对象生成自然语言回复）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState


@safe_node
async def render(state: AgentState) -> dict[str, Any]:
    """从 state 构造自然语言回复。"""
    # 子图已生成 reply_text → 透传
    if state.get("reply_text"):
        return {}
    # api_result 来自后端
    if state.get("api_result"):
        return {"reply_text": str(state["api_result"])}
    if state.get("error"):
        return {"reply_text": f"处理失败：{state['error']}"}
    if state.get("product_type") == "unknown":
        return {"reply_text": "未识别到有效指令，请明确指定产品（期权/互换）和操作（询价/下单/撤单等）。"}

    # 从结构化参数生成基础回复
    place = state.get("place_params") or {}
    close = state.get("close_params") or {}
    cancel = state.get("cancel_params") or {}

    if place.get("expected_action") == "inquiry":
        orders = place.get("orderList", [])
        if orders:
            o = orders[0]
            return {"reply_text": (
                f"-----场外期权询价详情-----\n"
                f"标的代码: {o.get('stockCode', 'N/A')}\n"
                f"期权类型: {o.get('optionType', 'N/A')}\n"
                f"期限: {o.get('tenor', 'N/A')}\n"
                f"执行价格: {o.get('strikePercentage', 'N/A')}%\n"
                f"期权费率: 6.9%\n名义本金: 待补充\n建仓指令: 待补充\n交易对手: 待补充\n\n"
                f"如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。"
            )}
    if close.get("closeOrderList"):
        return {"reply_text": "平仓申请已生成，请确认后回复【确认平仓】"}
    if cancel.get("cancelOrderNoList"):
        return {"reply_text": f"已收到撤单请求，订单号: {', '.join(cancel['cancelOrderNoList'])}"}

    return {}
