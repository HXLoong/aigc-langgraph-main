"""多轮对话 state 传递测试。

覆盖：
- Bug5: make_initial_state 不应把 tickers=[] 覆盖 checkpoint 里的 tickers
  （会导致 turn2 place_order_from_quote 误触发 zero-match 提示）
- tickers=None（未经历解析）不应触发 zero-match
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from app.graphs.main_graph import build_main_graph
from app.state import WechatInput, make_initial_state


# ============================================================
# Bug5: make_initial_state 不覆盖 checkpoint tickers
# ============================================================


def test_make_initial_state_does_not_set_tickers() -> None:
    """make_initial_state 返回的 dict 不应包含 tickers 键，
    防止每轮都把 checkpoint 里的 tickers 覆盖成空列表。
    """
    wx = WechatInput(
        conversation_id="c1",
        message_id="m1",
        room_id="r1",
        user_id="u1",
        guid="",
        raw_content="200万，市价下单",
    )
    state = make_initial_state(wx)
    assert "tickers" not in state, (
        "make_initial_state 不应设置 tickers——应保留 checkpoint 中已解析的值"
    )
