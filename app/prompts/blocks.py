"""提示词 user 消息的共享积木（ADR 0023）。

替代散落在 22 个节点里的 `_format_history` / `_format_shortname_list` / 手拼 f-string；
所有函数都是纯函数，只从 AgentState 已有字段取值。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.extraction.candidates import evidence_sources
from app.graph.state import Message


def format_history(history: Sequence[Message | dict[str, Any]] | None) -> str:
    """历史对话 → "role: content" 逐行；兼容 Message 模型与 dict（checkpoint 反序列化两种形态）。"""
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if isinstance(msg, Message) else msg.get("role", "user")
        content = msg.content if isinstance(msg, Message) else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def shortnames(counterparties: list[dict[str, Any]] | None) -> list[str]:
    """对手精简列表 → shortName 列表（跳过空值）。"""
    return [str(cp["shortName"]) for cp in (counterparties or []) if isinstance(cp, dict) and cp.get("shortName")]


def json_list(items: list[Any] | None) -> str:
    """列表 → JSON 文本（与 Dify code 节点 `json.dumps(..., ensure_ascii=False)` 同口径）。"""
    return json.dumps(items or [], ensure_ascii=False)


def source_payload(
    state: Mapping[str, Any], *, context: dict[str, Any] | None = None,
    attachments: dict[str, str] | None = None, include_history: bool = True,
) -> str:
    """One copy per evidence source, retaining IDs and roles without generated metadata."""
    selected = state if include_history else {**state, "history_messages": []}
    sources = evidence_sources(selected, attachments)
    ordered = {key: value for key, value in sources.items() if key not in {"raw", "quote"}}
    ordered.update(quote=sources["quote"], raw=sources["raw"])
    roles = {}
    for message in selected.get("history_messages") or []:
        ident = message.get("id") if isinstance(message, dict) else message.id
        role = message.get("role", "unknown") if isinstance(message, dict) else message.role
        key = f"history:{ident}"
        if key in ordered:
            roles[key] = role if role in {"user", "assistant", "system"} else "unknown"
    return json.dumps({"context": context or {}, "sources": ordered, "source_roles": roles},
                      ensure_ascii=False)


def kv_block(*pairs: tuple[str, Any], sep: str = "\n\n") -> str:
    """("key", value) 序列 → "key: value" 段落，None 渲染为空串。"""
    return sep.join(f"{k}: {'' if v is None else v}" for k, v in pairs)
