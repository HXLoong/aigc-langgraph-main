"""eval 与生产必须走同一条初始化路径（ADR 0024 D2：make_initial_state 退役）。

历史：app/state.py 的旧兼容层会硬清空 place_params / cancel_params / close_params、写 6 个
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


async def test_eval_pipeline_uses_production_turn_state(monkeypatch) -> None:
    """评测 HTTP 穿过真实 routes 输入适配，测试不另造状态初始化函数。"""
    import httpx

    from app.main import app
    from harness.golden import GoldenCase
    from harness.multi_turn import run_case_multi

    captured = {}
    class Graph:
        async def ainvoke(self, state, **kwargs):
            """只替换图执行，保留 HTTP 和生产输入映射。"""
            captured.update(state)
            return {**state, "reply_text": "ok", "trace": []}
    monkeypatch.setattr(app.state, "main_graph", Graph(), raising=False)
    case = GoldenCase(id="adapter", category="test", turns=[{"send_text": "询价", "at_bot": True, "quote_content": "Q"}])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=client)
    assert not result.failure
    assert captured["raw_text"] == "询价" and captured["quote_content"] == "Q"
    assert captured["conversation_id"] == result.conversation_id and captured["at_bot"] is True
    assert "place_params" not in captured and "bot_name_list" not in captured
