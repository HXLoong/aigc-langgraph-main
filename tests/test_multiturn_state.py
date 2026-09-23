"""eval 与生产必须走同一条初始化路径（ADR 0024 D2：make_initial_state 退役）。

历史：app/state.py 的 M1 兼容层会硬清空 place_params / cancel_params / close_params、写 6 个
AgentState 里不存在的键，只保护 tickers——eval 走它、生产走 routes._inputs_to_state，评估结论
与生产行为存在系统性偏差（CLAUDE.md 曾把它列为已知故障模式）。
"""
from __future__ import annotations

import importlib.util

from app.api.turn_state import inputs_to_state


def test_legacy_state_shim_is_gone() -> None:
    assert importlib.util.find_spec("app.state") is None, "app/state.py（make_initial_state）应已退役"


def test_inputs_to_state_is_the_single_turn_entry() -> None:
    state = inputs_to_state({"rawContent": "200万，市价下单", "messageId": 1, "roomId": "r", "userId": "u"})
    assert state["raw_text"] == "200万，市价下单"
    # 业务对象与历史由 checkpoint / ingest 管，入口不得写默认值
    for key in ("tickers", "place_params", "cancel_params", "close_params", "history_messages", "trace"):
        assert key not in state, key
    # 当轮语义字段显式置空，避免继承上轮路由 / 附件
    for key in ("fast_query", "existing_command", "at_bot", "quote_content", "quote_appinfo"):
        assert key in state and state[key] is None
    assert state["input_files"] == []


def test_eval_pipeline_uses_production_turn_state(monkeypatch) -> None:
    import asyncio

    from scripts.langfuse import langfuse_eval

    captured: dict = {}

    class _Graph:
        async def ainvoke(self, state, config, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(state)
            return {**state, "trace": []}

    asyncio.run(langfuse_eval._run_graph_once(
        _Graph(), {"configurable": {"thread_id": "t"}}, "询价", has_mention=True, quote_content="Q",
    ))
    assert captured["raw_text"] == "询价" and captured["quote_content"] == "Q"
    assert captured["conversation_id"] == "t" and captured["at_bot"] is True
    assert "place_params" not in captured and "bot_name_list" not in captured
