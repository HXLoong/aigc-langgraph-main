"""真实单节点图的输出、重试、私有 State 与 HTTP 客户端集成。"""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.graph.main import build_main_graph
from app.graph.retry import io_node
from app.graph.state import AgentState, Message, TickerCandidate
from app.main import app
from app.node_execution.executor import NodeExecutor
from app.node_execution.registry import NodeRegistration, build_registry
from app.subgraphs.close.graph import build_close_graph
from app.subgraphs.close.place_close import build_place_close_graph
from app.subgraphs.option.extract_inquiry import build_inquiry_graph
from app.subgraphs.option.graph import build_option_graph
from app.subgraphs.swap.graph import build_swap_graph
from app.subgraphs.swap.place_order import build_place_graph
from app.tools.message_client import MessageClientHttpx
from mock_api.server import app as mock_app
from tests.joint_support import instruction_data

_QUOTE_CARD = (
    "-----场外期权询价详情-----\r\n"
    "Q-20250616-000011\r\n"
    "标的代码：300098.SZ；欧式看涨；80%\r\n"
    "期限待补充，请引用本消息回复期限。如需下单，请提供建仓参数。"
)

CONTEXT = {"conversation_id": "nodes-test", "room_id": "room", "user_id": "user", "message_id": 1}


async def request(executor: NodeExecutor, product: str, node: str, state: dict) -> httpx.Response:
    app.state.node_executor = executor
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/v1/nodes/run", json={"product": product, "node": node, "state": state}
        )


async def request_business(executor: NodeExecutor, node: str, state: dict) -> httpx.Response:
    """经真实节点 HTTP 顺序执行参数准备、清洗和提交，保持每个节点的独立接口。"""
    prepared = await request(executor, "option", node, state)
    assert prepared.status_code == 200, prepared.text
    current = {**state, **prepared.json()["output"]}
    cleaned = await request(executor, "option", "option_clean_request", current)
    assert cleaned.status_code == 200, cleaned.text
    current.update(cleaned.json()["output"])
    submit = "option_query_backend" if current["pending_backend_request"]["intent"] == "query_order_status" else "option_submit"
    return await request(executor, "option", submit, current)


def test_catalog_matches_all_registered_graph_nodes_and_policies() -> None:
    graphs = [
        ("main", build_main_graph()),
        ("swap", build_swap_graph()),
        ("swap", build_place_graph()),
        ("option", build_option_graph()),
        ("option", build_inquiry_graph()),
        ("option_close", build_close_graph()),
        ("option_close", build_place_close_graph()),
    ]
    executor = NodeExecutor(build_registry())
    expected = set()
    for product, graph in graphs:
        for name, original in graph.builder.nodes.items():
            if original.is_error_handler:
                continue
            expected.add((product, name))
            actual = executor.graphs[(product, name)].builder.nodes[name]
            assert actual.retry_policy == original.retry_policy, (product, name)
            assert actual.error_handler_node == original.error_handler_node, (product, name)
    assert set(executor.registrations) == expected


@pytest.mark.parametrize("update", [{}, {"raw_text": "same"}, {"reply_text": None}])
async def test_exact_update_even_when_empty_or_unchanged(update: dict) -> None:
    async def target(state: AgentState) -> dict:
        assert "product_type" not in state
        return update

    executor = NodeExecutor(
        [NodeRegistration("main", "target", target, input_fields=("raw_text",))]
    )
    response = await request(executor, "main", "target", {"raw_text": "same"})
    assert response.status_code == 200
    assert response.json()["output"] == update


async def test_json_models_are_converted_before_node_and_serialized_after() -> None:
    async def target(state: AgentState) -> dict:
        assert isinstance(state["history_messages"][0], Message)
        assert isinstance(state["tickers"][0], TickerCandidate)
        return {"tickers": state["tickers"]}

    executor = NodeExecutor(
        [
            NodeRegistration(
                "main",
                "target",
                target,
                input_fields=("history_messages", "tickers"),
            )
        ]
    )
    response = await request(
        executor,
        "main",
        "target",
        {
            "history_messages": [{"role": "user", "content": "x"}],
            "tickers": [{"windCode": "00700.HK", "from_goats": True}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["output"]["tickers"][0]["windCode"] == "00700.HK"


async def test_concurrent_same_conversation_does_not_restore_or_share_state() -> None:
    async def target(state: AgentState) -> dict:
        await asyncio.sleep(0.001)
        return {
            "reply_text": state["raw_text"],
            "intent": str(len(state.get("history_messages", []))),
        }

    executor = NodeExecutor(
        [
            NodeRegistration(
                "main",
                "target",
                target,
                input_fields=("conversation_id", "raw_text", "history_messages"),
            )
        ]
    )
    results = await asyncio.gather(
        *[
            request(executor, "main", "target", {"conversation_id": "same", "raw_text": str(i)})
            for i in range(12)
        ]
    )
    assert [r.json()["output"] for r in results] == [
        {"reply_text": str(i), "intent": "0"} for i in range(12)
    ]
    assert executor.graphs[("main", "target")].checkpointer is False


@pytest.mark.parametrize(("private", "succeed"), [(False, False), (False, True), (True, False)])
async def test_io_retries_exactly_configured_attempts_and_exhaustion(
    private: bool,
    succeed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "node_retry_max_attempts", 3)
    monkeypatch.setattr(get_settings(), "node_retry_initial_interval_seconds", 0)
    calls = 0

    async def target(state: AgentState) -> dict:
        nonlocal calls
        calls += 1
        if succeed and calls == 3:
            return {"reply_text": "recovered"}
        raise httpx.ConnectError("offline")

    executor = NodeExecutor(
        [
            NodeRegistration(
                "main",
                "target",
                target if private else io_node(target),
                input_fields=(),
                io=True,
                with_error_handler=not private,
            )
        ]
    )
    response = await request(executor, "main", "target", {})
    assert calls == 3
    body = response.json()
    if succeed:
        assert response.status_code == 200
        assert body["output"]["reply_text"] == "recovered"
    elif private:
        assert response.status_code == 500
        assert "output" not in body
        assert body["error"] == {"type": "ConnectError", "message": "offline"}
    else:
        assert response.status_code == 500
        assert body["output"]["error"]["type"] == "ConnectError"
        assert body["output"]["trace"][0]["decision"] == "error:retry_exhausted"


async def test_private_place_close_fields_are_not_filtered() -> None:
    executor = NodeExecutor(build_registry())
    raw = "平仓 OPT-ABC"
    parsed = instruction_data("option_close", "close_order_request", raw, orders=[{"internalTradeId": "OPT-ABC"}])
    prepared = await request(executor, "option_close", "place_close_prepare", {"raw_text": raw, "parsed_instruction": parsed})
    assert prepared.status_code == 200, prepared.text
    orders = prepared.json()["output"]["pc_close_orders"]
    assert orders == [{"internalTradeId": "OPT-ABC"}]
    checked = await request(executor, "option_close", "place_close_validate", {"raw_text": raw, "pc_close_orders": orders})
    assert checked.status_code == 200, checked.text


async def test_persist_write_failure_keeps_existing_success_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = AsyncMock(side_effect=RuntimeError("db offline"))
    monkeypatch.setattr("app.nodes.persist.write_node_trace", writer)
    response = await request(
        NodeExecutor(build_registry()), "main", "persist", {"trace": [{"node": "old"}]}
    )
    assert response.status_code == 200, response.text
    assert "error" not in response.json()["output"]
    assert [t["node"] for t in response.json()["output"]["trace"]] == ["persist"]
    writer.assert_awaited_once()


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.inner = httpx.ASGITransport(app=mock_app)

    async def handle_async_request(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return await self.inner.handle_async_request(req)


async def test_persist_intent_skip_and_real_http_client() -> None:
    transport = RecordingTransport()
    skip = await request(NodeExecutor(build_registry()), "main", "persist_intent", {})
    assert skip.status_code == 200
    assert skip.json()["output"]["trace"][0]["decision"] == "skipped"
    executor = NodeExecutor(
        build_registry(
            lambda: MessageClientHttpx(
                base_url="http://mock",
                token="mock-only",
                transport=transport,
            )
        )
    )
    missing = await request(executor, "main", "persist_intent", {})
    assert missing.status_code == 422
    assert transport.requests == []
    written = await request(executor, "main", "persist_intent", CONTEXT | {"intent": "new_inquiry"})
    assert written.status_code == 200, written.text
    assert len(transport.requests) == 1
    assert transport.requests[0].url.path.endswith("/message/set-intent")
    assert json.loads(transport.requests[0].content)["conversationId"] == CONTEXT["conversation_id"]


@pytest.mark.parametrize("composite", [False, True])
async def test_option_real_client_to_http_mock_and_composite_output(
    composite: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.option_client import OptionClientHttpx

    transport = RecordingTransport()
    monkeypatch.setattr(
        "app.subgraphs.option.backend.OptionClientHttpx",
        lambda: OptionClientHttpx(
            base_url="http://mock",
            token="mock-only",
            transport=transport,
        ),
    )
    state = CONTEXT | {"raw_text": "查询订单 Q-20260921-1234567890",
        "parsed_instruction": instruction_data("option", "query_order_status", "查询订单 Q-20260921-1234567890")}
    executor = NodeExecutor(build_registry())
    response = (await request(executor, "main", "option", state) if composite
                else await request_business(executor, "option_extract_query", state))
    assert response.status_code == 200, response.text
    output = response.json()["output"]
    assert output["api_code"] == 0
    assert "raw_text" not in output
    assert "conversation_id" not in output
    assert "reply_text" not in output
    assert len(transport.requests) == 1


async def test_write_node_failure_calls_http_once_and_keeps_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.option_client import OptionClientHttpx

    calls = 0

    def offline(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=req)

    monkeypatch.setattr(
        "app.subgraphs.option.backend.OptionClientHttpx",
        lambda: OptionClientHttpx(
            base_url="http://mock",
            token="mock-only",
            transport=httpx.MockTransport(offline),
        ),
    )
    response = await request_business(
        NodeExecutor(build_registry()),
        "option_extract_confirm_place",
        CONTEXT | {"raw_text": "确认下单", "quote_content": _QUOTE_CARD,
            "parsed_instruction": instruction_data("option", "confirm_order", "确认下单",
                orders=[{"orderId": "Q-20250616-000011"}], quote=_QUOTE_CARD)},
    )
    assert response.status_code == 500, response.text
    assert calls == 1


async def test_business_rejection_is_unchanged_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.option_client import OptionClientHttpx

    monkeypatch.setattr(
        "app.subgraphs.option.backend.OptionClientHttpx",
        lambda: OptionClientHttpx(
            base_url="http://mock",
            token="mock-only",
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    json={
                        "code": 409,
                        "msg": "正在处理，请勿重复提交",
                        "data": None,
                    },
                )
            ),
        ),
    )
    response = await request_business(
        NodeExecutor(build_registry()),
        "option_extract_confirm_place",
        CONTEXT | {"raw_text": "确认下单", "quote_content": _QUOTE_CARD,
            "parsed_instruction": instruction_data("option", "confirm_order", "确认下单",
                orders=[{"orderId": "Q-20250616-000011"}], quote=_QUOTE_CARD)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["output"]["api_code"] == 409
    assert response.json()["output"]["api_result"] == "正在处理，请勿重复提交"




async def test_lifespan_uses_same_message_factory_for_both_apis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.main import lifespan

    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "use_mysql_checkpointer", False)
    transport = RecordingTransport()

    def message_factory() -> MessageClientHttpx:
        return MessageClientHttpx(base_url="http://mock", transport=transport)

    monkeypatch.setattr("app.main.MessageClientHttpx", message_factory)
    async with lifespan(app):
        response = await request(app.state.node_executor, "main", "persist_intent", CONTEXT)
        assert response.status_code == 200, response.text
        await app.state.main_graph.builder.nodes["persist_intent"].runnable.ainvoke(CONTEXT)
    assert len(transport.requests) == 2
    assert all(r.url.host == "mock" for r in transport.requests)


async def test_excel_input_node_downloads_and_preserves_all_cells(monkeypatch):
    """节点 HTTP 入口执行真实 Excel 读取，不进入交易或模型阶段。"""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["标的", "数量"])
    workbook.active.append(["茅台", 100])
    workbook.active.append(["平安", 200])
    buffer = io.BytesIO()
    workbook.save(buffer)
    downloads = []
    original = httpx.AsyncClient

    def asset(req):
        """只替换附件外部 HTTP，记录实际请求。"""
        downloads.append(req.url.path)
        return httpx.Response(200, content=buffer.getvalue())

    def factory(*args, **kwargs):
        """ASGI 测试传输保持原样，其余连接固定为附件响应。"""
        kwargs.setdefault("transport", httpx.MockTransport(asset))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    result = await request(NodeExecutor(build_registry()), "main", "prepare_input", {
        "input_files": [{"type": "document", "url": "http://assets/orders.xlsx"}]})
    assert result.status_code == 200, result.text
    output = result.json()["output"]
    assert downloads == ["/orders.xlsx"] and len(output["attachment_rows"]) == 2
    assert "茅台" in output["attachment_sources"]["file:0:sheet:0:row:2:column:A"]
    assert "200" in output["attachment_sources"]["file:0:sheet:0:row:3:column:B"]
    assert "place_params" not in output
