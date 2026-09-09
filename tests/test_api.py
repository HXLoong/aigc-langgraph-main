"""api/ 单元测试 — 验证 Dify Workflow Run API 兼容（ADR 0001 D3）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.api.routes as api_routes
from app.graph.state import TraceEntry
from app.main import app
from app.subgraphs.option import backend as option_backend
from app.subgraphs.swap import backend as swap_backend_module
from app.subgraphs.swap import intent as swap_intent_module
from app.subgraphs.swap import place_order as swap_place_order_module
from app.subgraphs.swap.models import SwapIntentOutput, SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution
from app.tools.models import CommonResult


class _CapturingGraph:
    """记录 API 入口传入的 state，避免字段映射测试依赖真实业务子图。"""

    def __init__(self) -> None:
        self.initial_state: dict | None = None
        self.config: dict | None = None

    async def ainvoke(self, state: dict, config: dict) -> dict:
        self.initial_state = state
        self.config = config
        return {
            **state,
            "product_type": "swap",
            "intent": "place_order_request",
            "reply_text": "BACKEND_CARD",
            "tickers": [],
            "trace": [TraceEntry(node="ingest", decision="ok")],
        }



@pytest.fixture()
def client():
    # 必须用 contextmanager 触发 lifespan（编译主图到 app.state）
    with TestClient(app) as c:
        # API 单元测试只验证协议与字段映射，不访问真实 LLM/Java 后端。
        c.app.state.main_graph = _CapturingGraph()
        yield c


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_workflows_run_returns_dify_compatible_schema(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0001 D3：response 必须符合 Dify 协议形态。"""

    def fake_structured_llm(value: object) -> MagicMock:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=value)
        base = MagicMock()
        base.with_structured_output.return_value = llm
        return base

    monkeypatch.setattr(
        swap_intent_module,
        "get_qwen_thinking",
        lambda: fake_structured_llm(SwapIntentOutput(type="place_order_request")),
    )
    monkeypatch.setattr(
        swap_place_order_module,
        "get_qwen_complex",
        lambda: fake_structured_llm(SwapPlaceOrderParams(orderList=[])),
    )
    monkeypatch.setattr(
        swap_place_order_module,
        "resolve_ticker_full",
        AsyncMock(return_value=TickerResolution(resolved=[], hitl_pending=[])),
    )
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(return_value=MagicMock(code=0, data={}, msg=""))
    monkeypatch.setattr(swap_backend_module, "SwapClientHttpx", lambda: fake_client)
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "测试 - 互换下单",
                "conversationId": "c-test-001",
                "messageId": 42,
                "userId": "u-1",
                "roomId": "r-1",
                "messageContent": "测试 - 互换下单",
            },
            "response_mode": "blocking",
            "user": "c-test-001",
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    # Dify schema: workflow_run_id / task_id / data
    assert "workflow_run_id" in body
    assert "task_id" in body
    assert "data" in body

    data = body["data"]
    assert data["status"] == "succeeded"
    assert "outputs" in data
    assert data["total_steps"] >= 1  # 至少跑过 ingest

    # outputs 含 product_type / intent
    outputs = data["outputs"]
    assert outputs["product_type"] == "swap"  # M1 默认
    assert outputs["intent"] is not None


def test_workflows_run_returns_conversation_id_and_answer_at_top_level(
    client: TestClient,
) -> None:
    """Java 调用方可从响应顶层直接读取会话 ID 和最终回答。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "测试 - 互换下单",
                "conversationId": "c-top-level-001",
                "messageId": 42,
                "userId": "u-1",
                "roomId": "r-1",
                "messageContent": "测试 - 互换下单",
            },
            "response_mode": "blocking",
            "user": "c-top-level-001",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversationId"] == "c-top-level-001"
    assert isinstance(body["answer"], str)
    assert body["answer"] == body["data"]["outputs"]["reply_text"]


def test_development_response_exposes_matching_langfuse_trace_link(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = object()

    async def fake_trace_context(trace_id: str) -> tuple[object, str]:
        return handler, f"https://langfuse.test/project/p/traces/{trace_id}"

    monkeypatch.setattr(api_routes, "_development_langfuse_trace", fake_trace_context)

    response = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {"raw_content": "测试", "message_id": 1},
            "response_mode": "blocking",
            "user": "test-user",
        },
    )

    outputs = response.json()["data"]["outputs"]
    assert outputs["trace_url"].endswith(outputs["trace_id"])
    graph = client.app.state.main_graph
    assert graph.config is not None
    assert graph.config["callbacks"] == [handler]


def test_streaming_mode_rejected(client: TestClient) -> None:
    """blocking only（contracts §3：Java StockBotMessageServiceImpl.java:1646）。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {},
            "response_mode": "streaming",
            "user": "c-test",
        },
    )
    assert r.status_code == 400


def test_inputs_field_passthrough(client: TestClient) -> None:
    """Dify inputs 字段名应该兼容 camelCase 和 snake_case。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "snake_case 兼容性测试",  # 注意是 snake
                "conversationId": "c-snake",
                "messageId": 1,
                "userId": "u",
                "roomId": "r",
                "messageContent": "snake_case 兼容性测试",
            },
            "response_mode": "blocking",
            "user": "c-snake",
        },
    )
    assert r.status_code == 200


def test_workflows_run_normalizes_complete_snake_case_inputs(
    client: TestClient,
) -> None:
    """Dify 风格 snake_case 上下文必须完整进入 AgentState。"""
    graph = _CapturingGraph()
    client.app.state.main_graph = graph

    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "300773.SZ，欧式看涨，80%",
                "conversation_id": "c-snake-complete",
                "message_id": 123,
                "user_id": "u-snake",
                "room_id": "r-snake",
                "message_content": "300773.SZ，欧式看涨，80%",
                "quote_content": "quoted",
                "quote_appinfo": "meta",
                "guid": "g-snake",
            },
            "response_mode": "blocking",
            "user": "fallback-conversation",
        },
    )

    assert r.status_code == 200, r.text
    assert graph.initial_state is not None
    assert graph.initial_state["raw_text"] == "300773.SZ，欧式看涨，80%"
    assert graph.initial_state["conversation_id"] == "c-snake-complete"
    assert graph.initial_state["message_id"] == 123
    assert graph.initial_state["user_id"] == "u-snake"
    assert graph.initial_state["room_id"] == "r-snake"
    assert graph.initial_state["message_content"] == "300773.SZ，欧式看涨，80%"
    assert graph.initial_state["quote_content"] == "quoted"
    assert graph.initial_state["quote_appinfo"] == "meta"
    assert graph.initial_state["guid"] == "g-snake"


def test_workflows_run_preserves_complete_camel_case_inputs(
    client: TestClient,
) -> None:
    graph = _CapturingGraph()
    client.app.state.main_graph = graph

    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "300773.SZ，欧式看涨，80%",
                "conversationId": "c-camel",
                "messageId": 456,
                "userId": "u-camel",
                "roomId": "r-camel",
                "messageContent": "camel message",
                "quoteContent": "camel quote",
                "quoteAppinfo": "camel meta",
                "guid": "g-camel",
            },
            "response_mode": "blocking",
            "user": "fallback-conversation",
        },
    )

    assert r.status_code == 200, r.text
    assert graph.initial_state is not None
    assert graph.initial_state["raw_text"] == "300773.SZ，欧式看涨，80%"
    assert graph.initial_state["conversation_id"] == "c-camel"
    assert graph.initial_state["message_id"] == 456
    assert graph.initial_state["user_id"] == "u-camel"
    assert graph.initial_state["room_id"] == "r-camel"
    assert graph.initial_state["message_content"] == "camel message"
    assert graph.initial_state["quote_content"] == "camel quote"
    assert graph.initial_state["quote_appinfo"] == "camel meta"
    assert graph.initial_state["guid"] == "g-camel"


def test_first_turn_generates_conversation_id_and_followup_reuses_it(
    client: TestClient,
) -> None:
    first_graph = _CapturingGraph()
    client.app.state.main_graph = first_graph

    first_response = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "300773.SZ，欧式看涨，80%",
                "conversation_id": "",
                "message_id": 1,
                "user_id": "u-1",
                "room_id": "r-1",
            },
            "response_mode": "blocking",
            "user": "stable-user-key",
        },
    )

    assert first_response.status_code == 200, first_response.text
    generated_id = first_response.json()["conversationId"]
    assert str(UUID(generated_id)) == generated_id
    assert generated_id != "stable-user-key"
    assert first_graph.initial_state is not None
    assert first_graph.config is not None
    assert first_graph.initial_state["conversation_id"] == generated_id
    assert first_graph.config["configurable"]["thread_id"] == generated_id

    followup_graph = _CapturingGraph()
    client.app.state.main_graph = followup_graph
    followup_response = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "补充期限1M",
                "conversation_id": generated_id,
                "message_id": 2,
                "user_id": "u-1",
                "room_id": "r-1",
            },
            "response_mode": "blocking",
            "user": "stable-user-key",
        },
    )

    assert followup_response.status_code == 200, followup_response.text
    assert followup_response.json()["conversationId"] == generated_id
    assert followup_graph.initial_state is not None
    assert followup_graph.config is not None
    assert followup_graph.initial_state["conversation_id"] == generated_id
    assert followup_graph.config["configurable"]["thread_id"] == generated_id


@pytest.mark.parametrize("locations", [
    ("top",), ("camel",), ("snake",), ("top", "camel"),
    ("top", "snake"), ("camel", "snake"), ("top", "camel", "snake"),
])
@pytest.mark.parametrize("conversation_id", [
    "java-session-001", "(\\existing-id\\\\)", "  Opaque-ID/中文  ",
])
def test_conversation_id_is_reused_verbatim_across_supported_locations(
    client: TestClient, locations: tuple[str, ...], conversation_id: str,
) -> None:
    payload = {"inputs": {"raw_content": "你好"}, "user": "stable-user"}
    for location in locations:
        if location == "top":
            payload["conversation_id"] = conversation_id
        else:
            alias = "conversationId" if location == "camel" else "conversation_id"
            payload["inputs"][alias] = conversation_id

    response = client.post("/v1/workflows/run", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["conversationId"] == conversation_id
    graph = client.app.state.main_graph
    assert graph.initial_state["conversation_id"] == conversation_id
    assert graph.config["configurable"]["thread_id"] == conversation_id


@pytest.mark.parametrize("top,inputs", [
    ("java-id", {"conversationId": "different-id"}),
    ("java-id", {"conversation_id": "different-id"}),
    (None, {"conversationId": "java-id", "conversation_id": "different-id"}),
    ("java-id", {"conversationId": "java-id", "conversation_id": "different-id"}),
    ("java-id", {"conversationId": " java-id "}),
])
def test_conflicting_conversation_ids_return_422_without_running_graph(
    client: TestClient, top: str | None, inputs: dict,
) -> None:
    response = client.post("/v1/workflows/run", json={
        "conversation_id": top, "inputs": {"raw_content": "你好", **inputs},
        "user": "stable-user",
    })
    assert response.status_code == 422, response.text
    assert "conversation_id" in response.text
    assert client.app.state.main_graph.initial_state is None


@pytest.mark.parametrize("empty", [None, "", " \t "])
def test_empty_conversation_aliases_do_not_override_provided_id(
    client: TestClient, empty: str | None,
) -> None:
    response = client.post("/v1/workflows/run", json={
        "conversation_id": empty,
        "inputs": {"raw_content": "你好", "conversationId": empty,
                   "conversation_id": "java-id"},
        "user": "stable-user",
    })
    assert response.status_code == 200, response.text
    assert response.json()["conversationId"] == "java-id"


def test_top_level_user_fills_missing_backend_user_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_request = None

    class _Client:
        async def operate(self, request):
            nonlocal captured_request
            captured_request = request
            return CommonResult(code=0, data="BACKEND_CARD")

    class _BackendCallingGraph:
        async def ainvoke(self, state: dict, config: dict) -> dict:
            backend_result = await option_backend.call_option_backend(
                state,
                intent="new_inquiry",
                option_rfq={},
            )
            return {
                **state,
                **backend_result,
                "product_type": "option",
                "intent": "new_inquiry",
                "reply_text": backend_result["api_result"],
                "tickers": [],
                "trace": [],
            }

    monkeypatch.setattr(option_backend, "OptionClientHttpx", _Client)
    client.app.state.main_graph = _BackendCallingGraph()

    response = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "300773.SZ，欧式看涨，80%",
                "conversation_id": "",
                "message_id": 1,
                "room_id": "room-1",
            },
            "response_mode": "blocking",
            "user": "dify-user-1",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    assert captured_request is not None
    assert captured_request.user_id == "dify-user-1"


def test_workflows_run_rejects_conflicting_input_aliases(
    client: TestClient,
) -> None:
    """同一上下文字段的 camelCase/snake_case 值冲突时不得静默选一个。"""
    graph = _CapturingGraph()
    client.app.state.main_graph = graph

    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "camel value",
                "raw_content": "snake value",
            },
            "response_mode": "blocking",
            "user": "c-conflict",
        },
    )

    assert r.status_code == 422
    assert "raw_text" in r.text
    assert graph.initial_state is None


def test_workflows_run_emits_end_to_end_latency(client: TestClient) -> None:
    """#157：请求出口必须写端到端延迟直方图（无 node label，区别于节点级样本）。"""
    client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "测试 - 互换下单",
                "conversationId": "c-metrics-001",
                "messageId": 43,
                "userId": "u-1",
                "roomId": "r-1",
                "messageContent": "测试 - 互换下单",
            },
            "response_mode": "blocking",
            "user": "c-metrics-001",
        },
    )
    metrics_text = client.get("/metrics").text
    e2e_lines = [
        line
        for line in metrics_text.splitlines()
        if line.startswith("otc_agent_intent_latency_ms_count")
        and 'node="' not in line
        and 'product_type="swap"' in line
    ]
    assert e2e_lines, "端到端延迟样本（product_type=swap 且无 node label）未写入"
