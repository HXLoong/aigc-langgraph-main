"""BotContext：调业务后端所需的机器人上下文（ADR 0024 D3：协议层吃它，不吃 AgentState）。

三个子图的 backend 适配层曾各自维护一份 `_context()` / `_message_id()`；这里只定义一次。
节点仍把 AgentState 交给 `call_*_backend`，适配层在边界处 `BotContext.from_state()`，
其下的请求拼装只看这个模型——业务对象（tickers / place_params …）进不了协议层。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

#: 调写类 / 查类后端接口前必须齐全的字段（缺失 → MissingBackendContextError，不得静默跳过）
REQUIRED_FIELDS: tuple[str, ...] = ("conversation_id", "room_id", "user_id", "message_id")


def normalize_message_id(value: Any) -> int:
    """企微 message_id 可能是 int 或带前缀的字符串：只取数字位，最多 18 位；无数字 → 0。"""
    if isinstance(value, int):
        return value
    digits = "".join(ch for ch in str(value) if ch.isdigit()) if value is not None else ""
    return int(digits[-18:]) if digits else 0


class BotContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str = ""
    message_id: int = 0
    user_id: str = ""
    room_id: str = ""
    guid: str | None = None
    operator_user_id: str | None = None
    raw_text: str = ""
    quote_content: str | None = None
    quote_appinfo: str | None = None

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> BotContext:
        return cls(
            conversation_id=state.get("conversation_id", "") or "",
            message_id=normalize_message_id(state.get("message_id", 0)),
            user_id=state.get("user_id", "") or "",
            room_id=state.get("room_id", "") or "",
            guid=state.get("guid"),
            operator_user_id=state.get("operator_user_id"),
            raw_text=state.get("raw_text", "") or "",
            quote_content=state.get("quote_content"),
            quote_appinfo=state.get("quote_appinfo"),
        )

    def missing_required(self) -> list[str]:
        missing = [f for f in ("conversation_id", "room_id", "user_id") if not getattr(self, f)]
        if self.message_id <= 0:
            missing.append("message_id")
        return missing

    @property
    def message_content(self) -> str:
        """后端 messageContent：原文 + 换行 + 引用（有引用时）。"""
        return self.raw_text if not self.quote_content else f"{self.raw_text}\n{self.quote_content}"

    def to_wire(self) -> dict[str, Any]:
        """Java operate ReqVO 的上下文字段（camelCase），与历史 `_context()` 逐键一致。"""
        return {
            "conversationId": self.conversation_id,
            "messageId": self.message_id,
            "messageContent": self.message_content,
            "rawContent": self.raw_text,
            "quoteContent": self.quote_content,
            "quoteAppinfo": self.quote_appinfo,
            "userId": self.user_id,
            "roomId": self.room_id,
            "guid": self.guid,
            "operatorUserId": self.operator_user_id,
        }


__all__ = ["REQUIRED_FIELDS", "BotContext", "normalize_message_id"]
