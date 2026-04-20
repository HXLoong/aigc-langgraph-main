"""FastAPI 路由：企微消息回调 + 确认卡片回调 + 调试接口。"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import (
    ConfirmCallback,
    MessageResponse,
    WechatCallback,
)
from app.state import WechatInput, make_initial_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")


def _to_wechat_input(req: WechatCallback) -> WechatInput:
    return WechatInput(
        conversation_id=req.conversation_id,
        message_id=req.message_id,
        room_id=req.room_id,
        user_id=req.user_id,
        guid=req.guid,
        raw_content=req.raw_content,
        quote_content=req.quote_content,
        quote_appinfo=req.quote_appinfo,
        attachments=[a.model_dump() for a in req.attachments],
    )


@router.post("/message", response_model=MessageResponse)
async def handle_message(req: WechatCallback, request: Request) -> MessageResponse:
    """企微群消息回调入口。

    LangGraph thread_id 使用 conversation_id，保证同一会话的历史可被检索。
    在调用图之前，先从 checkpoint 读取历史对话，注入到初始 state。
    """
    graph_app = request.app.state.graph_app
    if graph_app is None:
        raise HTTPException(500, "Graph 未就绪")

    start = time.monotonic()
    state = make_initial_state(_to_wechat_input(req))

    # 预加载历史对话（从 checkpoint）
    from app.nodes.history import load_history_from_checkpoint

    try:
        history = await load_history_from_checkpoint(
            graph_app, req.conversation_id, max_turns=10,
        )
        state["history_messages"] = history
        logger.debug("预加载 %d 条历史消息 conv=%s",
                     len(history), req.conversation_id)
    except Exception as e:
        logger.warning("历史预加载失败（非致命）: %s", e)

    config: dict[str, Any] = {
        "configurable": {"thread_id": req.conversation_id},
        "recursion_limit": 25,
    }

    try:
        result = await graph_app.ainvoke(state, config=config)
    except Exception as e:
        logger.exception("Graph 执行异常 msg=%s", req.message_id)
        raise HTTPException(500, f"Graph 执行失败: {e}") from e

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "msg=%s product=%s intent=%s latency=%dms history=%d",
        req.message_id,
        result.get("product_type"),
        result.get("intent"),
        latency_ms,
        len(state.get("history_messages") or []),
    )

    return MessageResponse(
        reply=result.get("reply_text"),
        product_type=result.get("product_type"),
        intent=result.get("intent"),
        api_code=result.get("api_code"),
        error=result.get("error"),
        trace=result.get("trace", []),
    )


@router.post("/message/confirm")
async def handle_confirm(req: ConfirmCallback, request: Request) -> dict[str, Any]:
    """确认卡片回调：继续被 interrupt_before 暂停的图执行。

    LangGraph 通过 checkpoint 机制恢复 State，继续执行下一步。
    """
    graph_app = request.app.state.graph_app
    if graph_app is None:
        raise HTTPException(500, "Graph 未就绪")

    config = {"configurable": {"thread_id": req.conversation_id}}

    # 根据 action 注入确认/取消信号
    command_state = {
        "intent": "confirm_order" if req.action == "confirm" else "cancel_order_request",
        "order_ids": [req.order_id] if req.order_id else [],
    }

    # 更新 checkpoint，继续执行
    result = await graph_app.ainvoke(command_state, config=config)
    return {
        "reply": result.get("reply_text"),
        "api_code": result.get("api_code"),
    }


@router.get("/conversations/{conversation_id}/state")
async def get_conversation_state(conversation_id: str, request: Request) -> dict[str, Any]:
    """调试接口：查看某个会话的当前 State 快照。"""
    graph_app = request.app.state.graph_app
    if graph_app is None:
        raise HTTPException(500, "Graph 未就绪")

    config = {"configurable": {"thread_id": conversation_id}}
    snapshot = await graph_app.aget_state(config)
    if snapshot is None:
        return {"exists": False}

    return {
        "exists": True,
        "values": snapshot.values,
        "next_nodes": list(snapshot.next),
        "config": snapshot.config,
    }
