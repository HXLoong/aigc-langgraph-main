"""联合解析共用的来源定位，不转换业务字段。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evidence_sources(state: Mapping[str, Any], attachments: Mapping[str, str] | None = None) -> dict[str, str]:
    """为原文、引用、历史和附件建立唯一完整来源键。"""
    sources = {"raw": state.get("raw_text") or "", "quote": state.get("quote_content") or ""}
    for message in state.get("history_messages") or []:
        if isinstance(message, dict):
            ident, content = message.get("id"), message.get("content")
        else:
            ident, content = getattr(message, "id", None), getattr(message, "content", None)
        if isinstance(ident, str) and isinstance(content, str):
            sources[f"history:{ident}"] = content
    for reference, text in (attachments or {}).items():
        sources[f"attachment:{reference}"] = text
    return sources
