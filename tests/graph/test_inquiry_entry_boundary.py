"""询价入口由请求标志决定；普通询价的产品词不能触发 GOATS 快速解析。"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import get_settings
from app.graph import main
from app.graph.retry import io_node
from app.graph.state import AgentState
from app.nodes import fast_query
from app.subgraphs.option import extract_inquiry
from app.subgraphs.option import graph as option_graph
from app.tools.goats_agent_client import GoatsAgentClientHttpx
from app.tools.option_client import OptionClientHttpx
from tests.joint_support import joint_model

CONTEXT = {
    "conversation_id": "inquiry-entry", "message_id": 123,
    "room_id": "room", "user_id": "user", "robot_version": "V2", "at_bot": True,
}


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    async def send(
        self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any,
    ) -> httpx.Response:
        requests.append(request)
        if request.url.host == "goats.test":
            return httpx.Response(200, request=request, json={
                "errCode": {"code": 200}, "data": {"productType": "AUTOCALL", "tenor": ["1M"]},
            })
        assert request.url.host == "java.test", "unexpected external request"
        return httpx.Response(200, request=request, json={"code": 0, "data": "Java 询价回执"})

    # 截住两种客户端的 HTTP 边界，旧直连解析器也不能发出真实请求。
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    settings = get_settings().model_copy(update={
        "goats_base_url": "http://goats.test", "goats_client_id": "test-client",
        "goats_client_secret": "test-secret",
    })
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    client = OptionClientHttpx(base_url="http://java.test", token="test", dry_run=False)
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    monkeypatch.setattr(fast_query, "_make_option_client", lambda: client)
    monkeypatch.setattr(fast_query, "_make_agent_client", lambda: GoatsAgentClientHttpx(
        "http://goats.test", "test-client", "test-secret", "test-salt",
    ))
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    return requests


@pytest.mark.parametrize("flags", [{}, {"fast_query": "0"}])
@pytest.mark.parametrize("text", [
    "期权快速询价 欧式看涨 600519.SH 1M 100%",
    "期权雪球 600519.SH 1M 100%",
    "期权参与型看涨 600519.SH 1M 100%",
    "期权询价 敲入70% 600519.SH 1M 100%",
    "期权询价 敲出103% 600519.SH 1M 100%",
])
async def test_ordinary_inquiry_keywords_never_call_goats(
    monkeypatch: pytest.MonkeyPatch, wire: list[httpx.Request],
    flags: dict[str, str], text: str,
) -> None:
    @io_node
    async def classify(state: AgentState) -> dict[str, Any]:
        return {"intent": "new_inquiry"}

    monkeypatch.setattr(option_graph, "option_intent", classify)
    calls = []
    model = joint_model("option", "new_inquiry", orders=[{
        "stockCode": "600519.SH", "tenor": "1M", "strikePercentage": 100,
    }], calls=calls)
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: model)
    result = await main.build_main_graph().ainvoke({
        **CONTEXT, **flags, "raw_text": text, "message_content": text,
    })

    assert result.get("error") is None
    assert [request.url.host for request in wire] == ["java.test"]
    body = json.loads(wire[0].content)
    assert body["type"] == "new_inquiry" and body["operate"] == "询价"
    assert "optionRfq" not in body
    assert len(body["orderList"]) == 1 and body["orderList"][0]["stockCode"] == "600519.SH"
    assert body["rawContent"] == text
    assert len(calls) == 1
    stages = [entry.node for entry in result["trace"] if entry.node.startswith("inquiry_")]
    assert stages == ["inquiry_prepare", "inquiry_validate", "inquiry_submit"]
    assert result["reply_text"] == "Java 询价回执"


@pytest.mark.parametrize("existing,at_bot,branch", [
    (False, False, "quick_inquiry"),
    (True, False, "existing_command_query"),
    (True, True, "quick_inquiry"),
])
async def test_fast_flag_uses_goats_without_keyword_or_ordinary_inquiry(
    monkeypatch: pytest.MonkeyPatch, wire: list[httpx.Request],
    existing: bool, at_bot: bool, branch: str,
) -> None:
    model = MagicMock(side_effect=AssertionError("fast entry must not enter ordinary inquiry"))
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", model)
    result = await main.build_main_graph().ainvoke({
        **CONTEXT, "raw_text": "600519.SH 1M", "fast_query": "1",
        "existing_command": "1" if existing else "0", "at_bot": at_bot,
    })

    assert result.get("error") is None
    model.assert_not_called()
    assert result["entry_branch"] == branch
    if branch == "existing_command_query":
        assert [request.url.host for request in wire] == ["goats.test"]
        assert wire[0].url.path.endswith("/instruction/query")
        assert result["reply_text"] == "IGNORE_REQUEST_NOT_REPLY_USER"
        return
    assert [request.url.host for request in wire] == ["goats.test", "java.test"]
    assert wire[0].headers["agentid"] == "room@tl"
    assert wire[0].headers["agentsubid"] == "user"
    body = json.loads(wire[1].content)
    assert body["type"] == "new_inquiry" and body["operate"] == "询价"
    assert body["orderList"] == [] and body["optionRfq"]["tenor"] == ["1M"]
    assert result["entry_branch"] == "quick_inquiry"
    assert (result["product_type"], result["intent"]) == ("option", "new_inquiry")
    assert result["backend_request"] == body
    nodes = {entry.node for entry in result["trace"]}
    assert "quick_inquiry" in nodes
    assert not nodes.intersection({"pre_route", "intent_route", "option_intent", "inquiry_extract"})
    model.assert_not_called()


def test_ordinary_inquiry_graph_has_only_three_stages() -> None:
    graph = extract_inquiry.build_inquiry_graph().get_graph()
    assert set(graph.nodes) == {
        "__start__", "inquiry_prepare", "inquiry_validate", "inquiry_submit", "__end__",
    }
    assert len(graph.edges) == 6
