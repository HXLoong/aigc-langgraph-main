"""意图集两种执行模式的判定（纯函数，无 app 依赖，lint 与 runner 共用）。

- 冻结（intent_chain）：每轮上下文写死在 fixture（quote_content / history / prev_product_type），
  只跑意图子链、只调 LLM（harness/intent_runner.py）
- 回放（replay）：子轮引用上一轮真实回复（quote_previous 非 False 且未冻结引用），或正文含
  `{{previous_*}}` 动态引用；必须走主图 + 后端（CI 为 mock_api）才能拿到上一轮回复
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: 冻结上下文字段；在回放模式下会被忽略，所以同一用例不能与回放混用
FROZEN_CONTEXT_FIELDS = ("quote_content", "history", "prev_product_type")
_DYNAMIC_REFERENCE = "{{previous_"


def turn_requires_replay(index: int, turn: Mapping[str, Any]) -> bool:
    if _DYNAMIC_REFERENCE in str(turn.get("send_text") or ""):
        return True
    # 首轮没有上一轮回复可引；子轮 quote_previous 缺省（None）= 引用第 1 轮回复
    return index > 0 and turn.get("quote_previous") is not False and not turn.get("quote_content")


def requires_replay(turns: Sequence[Mapping[str, Any]]) -> bool:
    """任一轮需要上一轮真实回复 → 整条用例走回放模式。"""
    return any(turn_requires_replay(index, turn) for index, turn in enumerate(turns))


def has_frozen_context(turns: Sequence[Mapping[str, Any]]) -> bool:
    return any(turn.get(field) for turn in turns for field in FROZEN_CONTEXT_FIELDS)


__all__ = ["FROZEN_CONTEXT_FIELDS", "has_frozen_context", "requires_replay", "turn_requires_replay"]
