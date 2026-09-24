"""评测输入应带真实协议的参考上下文，并解析声明的跨轮单号。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from scripts.langfuse import langfuse_eval as ev


async def test_intent_turn_loads_both_counterparty_contexts_through_real_client(monkeypatch):
    from app.tools.ticker_client import TickerClientHttpx

    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "data": [{
            "shortName": "期权测试账户" if request.url.params["type"] == "OPTION" else "互换测试账户",
            "ctptyId": 1,
        }]})
    client = TickerClientHttpx(base_url="http://mock", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ev, "TickerClientHttpx", lambda: client, raising=False)
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value={}))
    await ev._run_graph_once(graph, {"configurable": {"thread_id": "c"}}, "买入", suite="intent")
    state = graph.ainvoke.call_args.args[0]
    assert len(seen) == 2
    assert {r.url.params["type"] for r in seen} == {"OPTION", "TRS"}
    assert all(int(r.url.params["messageId"]) == state["message_id"] for r in seen)
    assert "期权测试账户" in state["option_counterparties_raw"]
    assert "互换测试账户" in state["swap_counterparties_raw"]


async def test_pipeline_resolves_previous_order_reference_before_graph_call(monkeypatch):
    calls = []
    order_id = "Q-20260923-0000000001"
    class Graph:
        async def ainvoke(self, state, config):
            calls.append(state)
            return {"reply_text": f"单号：{order_id}", "product_type": "option", "intent": "query_order_status"}
    monkeypatch.setattr(ev, "build_main_graph", lambda _cp: Graph())
    monkeypatch.setattr(ev, "_TURN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(ev, "_graph_callbacks", lambda: [])
    item = SimpleNamespace(input={"send_text": "查询期权订单", "sub_scenes": [{
        "send_text": "查询 {{previous_order_id}} 状态", "quote_previous": True,
    }]})
    output = await ev.run_langgraph_pipeline(item=item)
    assert calls[1]["raw_text"] == f"查询 {order_id} 状态"
    assert output["turns"][1]["raw_content"] == calls[1]["raw_text"]


async def test_pipeline_stops_on_ambiguous_previous_order_reference(monkeypatch):
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value={
        "reply_text": "单号：Q-20260923-0000000001\n单号：Q-20260923-0000000002",
    }))
    monkeypatch.setattr(ev, "build_main_graph", lambda _cp: graph)
    monkeypatch.setattr(ev, "_TURN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(ev, "_graph_callbacks", lambda: [])
    output = await ev.run_langgraph_pipeline(item=SimpleNamespace(input={
        "send_text": "询价", "sub_scenes": [{"send_text": "查询 {{previous_order_id}}"}],
    }))
    assert graph.ainvoke.await_count == 1
    assert output["failure"]["turn"] == 2
    assert "唯一订单号" in output["failure"]["error"]["message"]
