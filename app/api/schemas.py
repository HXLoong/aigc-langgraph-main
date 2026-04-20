"""API 请求/响应 schema。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AttachmentItem(BaseModel):
    """附件信息（图片/Excel URL）。"""
    url: str
    remote_url: str | None = None
    filename: str | None = None
    type: str | None = None   # image / excel


class WechatCallback(BaseModel):
    """企微回调入参。"""
    conversation_id: str = Field(..., description="企微会话 ID，作为 LangGraph thread_id")
    message_id: str
    room_id: str
    user_id: str
    guid: str = ""
    raw_content: str
    quote_content: str | None = None
    quote_appinfo: str | None = None
    attachments: list[AttachmentItem] = Field(default_factory=list)


class TraceItem(BaseModel):
    node: str
    status: str | None = None
    decision: str | None = None
    duration_ms: int | None = None
    error: str | None = None


class MessageResponse(BaseModel):
    """回复给企微机器人的响应。"""
    reply: str | None = None
    product_type: str | None = None
    intent: str | None = None
    api_code: int | None = None
    error: str | None = None
    trace: list[TraceItem] = Field(default_factory=list)


class ConfirmCallback(BaseModel):
    """用户点击确认卡片按钮后的回调。"""
    conversation_id: str
    action: str   # confirm / cancel
    order_id: str | None = None
