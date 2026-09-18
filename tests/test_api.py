"""api/ 单元测试 — 验证 Dify Workflow Run API 兼容（ADR 0001 D3）。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.api.routes as api_routes
from app.graph.state import TraceEntry
from app.main import app
from app.observability import tracing as observability_tracing
from app.observability.tracing import RequestTrace
from app.subgraphs.option import backend as option_backend
from app.subgraphs.swap import backend as swap_backend_module
from app.subgraphs.swap import intent as swap_intent_module
from app.subgraphs.swap import place_order as swap_place_order_module
from app.subgraphs.swap.models import SwapIntentOutput, SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution


class _CapturingGraph:
    """记录 API 入口传入的 state，避免字段映射测试依赖真实业务子图。"""

    def __init__(self) -> None:
        self.initial_state: dict | None = None
        self.config: dict | None = None
        self.invoke_kwargs: dict | None = None

    async def ainvoke(self, state: dict, config: dict, **kwargs: object) -> dict:
        self.initial_state = state
        self.config = config
        self.invoke_kwargs = dict(kwargs)
        return {
            **state,
            "product_type": "swap",
            "intent": "place_order_request",
            "reply_text": "BACKEND_CARD",
            "tickers": [],
            "api_code": 0,
            "api_result": "BACKEND_OK",
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
    fake_client.operate = AsyncMock(return_value={"code": 0, "data": {}, "msg": ""})
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
    # 核销凭据（plan0909 R2）：HTTP 形态下状态码 / 后端结果 / 节点链可判定
    assert outputs["api_code"] == 0
    assert outputs["api_result"] == "BACKEND_OK"
    assert outputs["trace"] == "ingest[ok]"


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
    langfuse_trace_id = "f" * 32

    async def fake_attach(
        *, request_trace_id: str, traceparent: str | None
    ) -> RequestTrace:
        assert traceparent is None
        return RequestTrace(
            handler=handler,
            langfuse_trace_id=langfuse_trace_id,
            url=f"https://langfuse.test/project/p/traces/{langfuse_trace_id}",
        )

    monkeypatch.setattr(api_routes, "attach_request_trace", fake_attach)

    response = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {"raw_content": "测试", "message_id": 1},
            "response_mode": "blocking",
            "user": "test-user",
        },
    )

    outputs = response.json()["data"]["outputs"]
    # 业务审计 ID 恒定存在，且与 LangFuse 侧 ID 分离
    assert len(outputs["trace_id"]) == 32
    assert outputs["trace_id"] != outputs["langfuse_trace_id"]
    assert outputs["langfuse_trace_id"] == langfuse_trace_id
    assert outputs["trace_url"].endswith(outputs["langfuse_trace_id"])
    graph = client.app.state.main_graph
    assert graph.config is not None
    # ADR 0024 D5：LLM 指标 callback 常驻，LangFuse handler 并列
    from app.observability.llm_metrics import LLMMetricsCallback

    assert handler in graph.config["callbacks"]
    assert any(isinstance(cb, LLMMetricsCallback) for cb in graph.config["callbacks"])


def test_test_workbench_request_joins_case_trace(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_trace_id = "1" * 32
    parent_span_id = "2" * 16
    traceparent = f"00-{parent_trace_id}-{parent_span_id}-01"
    captured: dict[str, str | None] = {}

    async def fake_attach(
        *, request_trace_id: str, traceparent: str | None
    ) -> RequestTrace:
        captured["request_trace_id"] = request_trace_id
        captured["traceparent"] = traceparent
        return RequestTrace(handler=object(), langfuse_trace_id=parent_trace_id)

    monkeypatch.setattr(api_routes, "attach_request_trace", fake_attach)

    response = client.post(
        "/v1/workflows/run",
        headers={"traceparent": traceparent},
        json={
            "conversation_id": "ai-test-case-1",
            "inputs": {"raw_content": "第二轮", "message_id": 2},
            "response_mode": "blocking",
            "user": "test-user",
        },
    )

    outputs = response.json()["data"]["outputs"]
    assert captured["traceparent"] == traceparent
    assert captured["request_trace_id"] != parent_trace_id
    # 父 Trace 不得覆盖业务审计 ID —— 本次重构的核心不变量
    assert outputs["trace_id"] == captured["request_trace_id"]
    assert outputs["langfuse_trace_id"] == parent_trace_id


def _patch_langfuse(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, object],
) -> None:
    """把 tracing 模块的 langfuse 依赖替换成 fake。"""

    class FakeCallbackHandler:
        def __init__(self, **kwargs: object) -> None:
            captured["handler"] = kwargs

    class FakeLangfuse:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs

        def get_trace_url(self, *, trace_id: str) -> str:
            return f"https://langfuse.test/project/p/traces/{trace_id}"

    monkeypatch.setattr(
        observability_tracing,
        "get_settings",
        lambda: SimpleNamespace(
            environment="development",
            enable_langfuse=True,
            langfuse_public_key="public",
            langfuse_secret_key="secret",
            langfuse_base_url="https://langfuse.test",
            trust_inbound_traceparent=True,  # 测试工作台场景：信任父 Trace（ADR 0024 D5 独立开关）
        ),
    )
    monkeypatch.setattr(observability_tracing, "_langfuse_client", None)
    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))
    monkeypatch.setitem(
        sys.modules,
        "langfuse.langchain",
        SimpleNamespace(CallbackHandler=FakeCallbackHandler),
    )
    monkeypatch.setitem(
        sys.modules, "langfuse.types", SimpleNamespace(TraceContext=dict)
    )


@pytest.mark.asyncio
async def test_self_created_trace_reuses_request_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自建 Trace 时 LangFuse trace id 复用业务 request_trace_id（ADR 0004/#156）。"""
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)

    trace = await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32, traceparent=None
    )

    assert trace.langfuse_trace_id == "3" * 32
    assert trace.url == "https://langfuse.test/project/p/traces/" + "3" * 32
    assert captured["handler"] == {
        "public_key": "public",
        "trace_context": {"trace_id": "3" * 32},
    }


@pytest.mark.asyncio
async def test_parent_trace_context_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """development 环境接入调用方传入的父 Trace。"""
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)
    parent_trace_id = "1" * 32
    span_id = "2" * 16

    trace = await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32,
        traceparent=f"00-{parent_trace_id}-{span_id}-01",
    )

    assert trace.langfuse_trace_id == parent_trace_id
    assert trace.url is None  # 父 Trace 模式不查链接
    assert captured["handler"] == {
        "public_key": "public",
        "trace_context": {"trace_id": parent_trace_id, "parent_span_id": span_id},
    }


@pytest.mark.asyncio
async def test_traceparent_ignored_unless_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0024 D5：traceparent 信任由独立开关 trust_inbound_traceparent 承担，不再绑死 environment；
    LangFuse 请求级 trace 在生产同样生效（此前生产走裸 CallbackHandler，trace_id 契约是死码）。"""
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)
    monkeypatch.setattr(
        observability_tracing,
        "get_settings",
        lambda: SimpleNamespace(
            environment="production",
            enable_langfuse=True,
            langfuse_public_key="public",
            langfuse_secret_key="secret",
            langfuse_base_url="https://langfuse.test",
            trust_inbound_traceparent=False,
        ),
    )
    trace = await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32, traceparent=f"00-{'1' * 32}-{'2' * 16}-01"
    )
    assert trace.handler is not None, "生产环境也必须接入请求级 trace"
    assert trace.langfuse_trace_id == "3" * 32  # 未信任 → 自建 trace，忽略父 trace


@pytest.mark.asyncio
async def test_traceparent_used_when_trusted_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)
    monkeypatch.setattr(
        observability_tracing,
        "get_settings",
        lambda: SimpleNamespace(
            environment="production",
            enable_langfuse=True,
            langfuse_public_key="public",
            langfuse_secret_key="secret",
            langfuse_base_url="https://langfuse.test",
            trust_inbound_traceparent=True,
        ),
    )
    trace = await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32, traceparent=f"00-{'1' * 32}-{'2' * 16}-01"
    )
    assert trace.langfuse_trace_id == "1" * 32
    assert captured["client"]["environment"] == "production"


@pytest.mark.asyncio
async def test_trace_unavailable_degrades_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """langfuse 不可用时返回空 RequestTrace —— 绝不阻断业务。"""
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", None)

    trace = await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32, traceparent=None
    )

    assert trace.handler is None
    assert trace.langfuse_trace_id is None
    assert trace.url is None


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
            return {"code": 0, "data": "BACKEND_CARD"}

    class _BackendCallingGraph:
        async def ainvoke(self, state: dict, config: dict, **kwargs: object) -> dict:
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


def test_graph_invoked_with_exit_durability(client: TestClient) -> None:
    """ADR 0024 D4：图内无 interrupt，单轮无需中途恢复；durability="exit" 把每轮
    十几次 superstep 落盘降到退出时一次，语义零损失。"""
    client.post("/v1/workflows/run", json={"inputs": {"rawContent": "100万"}, "user": "u-1"})
    graph = client.app.state.main_graph
    assert graph.invoke_kwargs is not None
    assert graph.invoke_kwargs.get("durability") == "exit"


def test_run_config_carries_langfuse_session_and_user(client: TestClient) -> None:
    client.post(
        "/v1/workflows/run",
        json={"inputs": {"rawContent": "100万", "conversationId": "conv-9", "userId": "u-9"}, "user": "u-9"},
    )
    md = client.app.state.main_graph.config["metadata"]
    assert md["langfuse_session_id"] == "conv-9"
    assert md["langfuse_user_id"] == "u-9"


@pytest.mark.asyncio
async def test_langfuse_client_registered_before_handler_on_parent_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tracing.py 缺陷：CallbackHandler(public_key=) 内部 get_client 只在已注册实例里查，
    父 Trace 分支此前提前 return、从不调用 _ensure_client → handler 静默 no-op。"""
    captured: dict[str, object] = {}
    _patch_langfuse(monkeypatch, captured)
    order: list[str] = []
    real_ensure = observability_tracing._ensure_client

    def _ensure() -> object:
        order.append("client")
        return real_ensure()

    monkeypatch.setattr(observability_tracing, "_ensure_client", _ensure)
    fake_handler_cls = sys.modules["langfuse.langchain"].CallbackHandler
    original_init = fake_handler_cls.__init__

    def _init(self: object, **kwargs: object) -> None:
        order.append("handler")
        original_init(self, **kwargs)

    monkeypatch.setattr(fake_handler_cls, "__init__", _init)

    await observability_tracing.attach_request_trace(
        request_trace_id="3" * 32, traceparent=f"00-{'1' * 32}-{'2' * 16}-01"
    )
    assert order[:2] == ["client", "handler"], order


@pytest.mark.asyncio
async def test_langfuse_callback_runs_inline_for_current_span_updates(monkeypatch):
    captured = {}
    _patch_langfuse(monkeypatch, captured)
    monkeypatch.setattr(observability_tracing, "get_settings", lambda: SimpleNamespace(
        environment="development", enable_langfuse=True, langfuse_public_key="public",
        langfuse_secret_key="secret", langfuse_base_url="https://langfuse.test",
        trust_inbound_traceparent=False,
    ))
    trace = await observability_tracing.attach_request_trace(request_trace_id="4"*32, traceparent=None)
    assert trace.handler.run_inline is True
