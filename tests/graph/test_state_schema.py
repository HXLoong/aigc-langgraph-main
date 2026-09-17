"""AgentState schema 守护（ADR 0024 D2）。"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

from app.graph.state import AgentState

_STATE_FILE = Path(__file__).resolve().parents[2] / "app" / "graph" / "state.py"


def _agent_state_declared_keys() -> list[str]:
    tree = ast.parse(_STATE_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AgentState":
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    raise AssertionError("AgentState 未找到")


def test_agent_state_has_no_duplicate_field_declarations() -> None:
    """reply_text 曾被声明两次（两段注释块各写一遍），说明 TypedDict 已无人通读。"""
    keys = _agent_state_declared_keys()
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"AgentState 重复声明字段：{dupes}"


def test_api_result_type_admits_backend_payload_shapes() -> None:
    """后端 result.data 可能是 dict / list / str（swap/backend.py、close/backend.py），
    声明为 str 会让 render / place_order_submit 的 isinstance 分支与类型撒谎。"""
    hint = get_type_hints(AgentState)["api_result"]
    args = set(getattr(hint, "__args__", ()))
    assert dict in args or any(getattr(a, "__origin__", None) is dict for a in args)
    assert list in args or any(getattr(a, "__origin__", None) is list for a in args)
