"""按 id 合并的 reducer（ADR 0024 D3：原生子图嵌入的前提）。

原生子图节点会把完整输出 state 交回父图；若 trace / history_messages 仍用 operator.add，
父图已有的条目会被再加一遍。LangGraph 对 messages 的解法是按 id 合并，这里同款。
"""
from __future__ import annotations

from app.graph.state import Message, TraceEntry, merge_by_id


def test_trace_entry_has_id_but_id_is_excluded_from_dump_and_equality() -> None:
    a, b = TraceEntry(node="x"), TraceEntry(node="x")
    assert a.id != b.id
    assert "id" not in a.model_dump()
    assert a == b, "id 不参与相等比较（测试与 differ 只关心内容）"


def test_message_has_id_excluded_from_dump() -> None:
    m = Message(role="user", content="hi")
    assert m.id and "id" not in m.model_dump()
    assert m == Message(role="user", content="hi")


def test_merge_by_id_dedupes_entries_already_in_left() -> None:
    a, b, c = TraceEntry(node="a"), TraceEntry(node="b"), TraceEntry(node="c")
    merged = merge_by_id([a, b], [a, b, c])  # 子图回传含父图已有的 a、b
    assert [e.node for e in merged] == ["a", "b", "c"]


def test_merge_by_id_uses_id_not_object_identity() -> None:
    a = TraceEntry(node="a")
    a_copy = TraceEntry.model_validate({"node": "a", "id": a.id})
    assert a_copy is not a and a_copy.id == a.id
    assert [e.node for e in merge_by_id([a], [a_copy])] == ["a"]


def test_merge_by_id_falls_back_to_identity_for_dicts() -> None:
    d = {"node": "legacy"}
    assert merge_by_id([d], [d, {"node": "other"}]) == [d, {"node": "other"}]


def test_merge_by_id_keeps_plain_append_semantics() -> None:
    assert merge_by_id([], [TraceEntry(node="a")])[0].node == "a"
    assert merge_by_id([TraceEntry(node="a")], []) != []


# ============================================================
# history_messages 窗口 reducer（ADR 0024 D4：企微群 thread 长期存在，历史不能无界）
# ============================================================


def test_merge_history_keeps_only_last_n(monkeypatch) -> None:
    from typing import get_type_hints

    from app.graph import state as state_mod
    from app.graph.state import AgentState, merge_history

    monkeypatch.setattr(state_mod, "_history_window", lambda: 4)
    left = [Message(role="user", content=str(i)) for i in range(3)]
    right = [Message(role="assistant", content="a"), Message(role="user", content="b")]
    merged = merge_history(left, right)
    assert [m.content for m in merged] == ["2", "a", "b"][-4:] or [m.content for m in merged] == ["1", "2", "a", "b"]
    assert len(merged) == 4
    # 仍按 id 去重（原生子图回传完整 history 时不重复）
    assert len(merge_history(merged, merged)) == 4
    # AgentState 用的就是这个 reducer
    hint = get_type_hints(AgentState, include_extras=True)["history_messages"]
    assert hint.__metadata__[0] is merge_history


def test_history_window_default_comes_from_settings() -> None:
    from app.config import Settings
    from app.graph.state import _history_window

    assert Settings.model_fields["history_window_messages"].default == 40
    assert _history_window() >= 2
