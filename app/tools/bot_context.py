"""BotContext：调业务后端所需的机器人上下文（ADR 0024 D3：协议层吃它，不吃 AgentState）。

三个子图的 backend 适配层共用这里的上下文定义（`to_wire()` / `normalize_message_id`）。
节点仍把 AgentState 交给 `call_*_backend`，适配层在边界处 `BotContext.from_state()`，
其下的请求拼装只看这个模型——业务对象（tickers / place_params …）进不了协议层。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

#: 调写类 / 查类后端接口前必须齐全的字段（缺失 → MissingBackendContextError，不得静默跳过）
REQUIRED_FIELDS: tuple[str, ...] = ("conversation_id", "room_id", "user_id", "message_id")


def normalize_message_id(value: Any) -> int:
    """保留 Java Long 范围内的完整 ID；旧带前缀形式仍提取数字，但不截断。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value)
    else:
        digits = "".join(ch for ch in str(value) if ch.isdigit()) if value is not None else ""
        number = int(digits) if digits else 0
    if number > 9223372036854775807:
        raise ValueError("message_id exceeds Java Long range; refusing to truncate")
    return number


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
        present = {field: bool(getattr(self, field)) for field in REQUIRED_FIELDS}
        present["message_id"] = self.message_id > 0
        return [field for field in REQUIRED_FIELDS if not present[field]]

    @classmethod
    def missing_required_from_state(cls, state: Mapping[str, Any]) -> list[str]:
        """不要求 State 已完成类型校验，供准备接口聚合全部诊断。"""
        present = {
            field: isinstance(state.get(field), str) and bool(state.get(field))
            for field in REQUIRED_FIELDS
        }
        present["message_id"] = normalize_message_id(state.get("message_id")) > 0
        return [field for field in REQUIRED_FIELDS if not present[field]]

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
