"""真实 HTTP/主图/checkpoint 链路；仅外部 LLM、Java HTTP 与数据库使用替身。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.main as app_main
from app.config import get_settings
from app.subgraphs.option.models import (
    OptionInquiryParams,
    OptionIntentOutput,
    OptionPlaceParams,
)
from app.tools.message_client import MessageClientHttpx
from app.tools.option_client import OptionClientHttpx
from app.tools.swap_client import SwapClientHttpx
from app.tools.ticker_client import TickerClientHttpx

FIRST_MESSAGE = "300773.SZ，欧式看涨，80%"
INQUIRY_CARD = (
    "-----场外期权询价详情-----\r\n"
    "Q-20260907-000001\r\n标的代码：300773.SZ；欧式看涨；80%\r\n"
    "期限待补充，请引用本消息回复期限。如需下单，请提供建仓参数。\r\n"
)
UPDATED_CARD = "  -----场外期权询价详情-----\r\nQ-20260907-000001\r\n期限：1M\r\n"


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, factory: str,
    schema: type[BaseModel], outputs: list[dict[str, Any]],
) -> AsyncMock:
    invoke = AsyncMock(side_effect=[schema.model_validate(item) for item in outputs])
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(factory, lambda: llm)
    return invoke


@pytest.fixture()
def inquiry_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, list[tuple[str, dict[str, Any]]]]]:
    from langgraph.checkpoint.memory import InMemorySaver

    settings = get_settings().model_copy(update={
        "environment": "staging", "use_mysql_checkpointer": True,
        "enable_langfuse": False,
    })
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    monkeypatch.setenv("ENABLE_LANGFUSE", "false")
    monkeypatch.setattr(app_main, "init_checkpointer", AsyncMock(return_value=InMemorySaver()))
    monkeypatch.setattr(app_main, "close_checkpointer", AsyncMock())
    monkeypatch.setattr("app.nodes.persist._write_to_mysql", AsyncMock())

    # 保留真实 tokenizer / resolver / ticker HTTP，仅替换外部 LLM。
    async def ticker_llm_response(messages):
        content = messages[-1].content
        result = {"300773.SZ": ["300773.SZ"]} if "300773" in content else {}
        return MagicMock(content=json.dumps(result))

    infer_llm = MagicMock()
    infer_llm.ainvoke = AsyncMock(side_effect=ticker_llm_response)
    monkeypatch.setattr("app.subgraphs.ticker.tools.get_qwen_standard", lambda: infer_llm)
    from app.nodes.intent_route import UnknownIntentOutput
    _patch_llm(monkeypatch, "app.nodes.intent_route.get_qwen_thinking",
               UnknownIntentOutput, [{"label": "\u671f\u6743-\u6587\u672c"}] * 3)
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        if path.endswith("/securities-instrument/select"):
            keyword = payload["keywordItems"][0]["keyword"]
            data = [{"windCode": "300773.SZ", "insShtDesc": "拉卡拉"}] if keyword in (
                "300773.SZ", "300773",
            ) else []
        elif path.endswith("/instrument-inference-prompt"):
            data = ""
        elif path.endswith(("/financial-orders/operate", "/swap-order/operate")):
            calls.append(("operate", payload))
            data = INQUIRY_CARD if payload["rawContent"] == FIRST_MESSAGE else UPDATED_CARD
        elif path.endswith("/message/set-intent"):
            calls.append(("set-intent", payload))
            data = True
        else:
            raise AssertionError(f"Unexpected HTTP path: {path}")
        return httpx.Response(200, json={"code": 0, "data": data})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: OptionClientHttpx(
        base_url="https://java.invalid", token="", transport=transport, dry_run=False,
    ))
    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx", lambda: OptionClientHttpx(
        base_url="https://java.invalid", token="", transport=transport, dry_run=False,
    ))
    monkeypatch.setattr(app_main, "MessageClientHttpx", lambda: MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=transport,
    ))
    monkeypatch.setattr("app.subgraphs.swap.backend.SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="https://java.invalid", token="", transport=transport, dry_run=False,
    ))
    monkeypatch.setattr("app.subgraphs.ticker.tools.TickerClientHttpx", lambda **kw: TickerClientHttpx(
        base_url="https://java.invalid", token="", transport=transport,
    ))
    with TestClient(app_main.app) as client:
        yield client, calls


@pytest.mark.parametrize("top,aliases,expected_id", [
    ({}, {}, None),
    ({"conversation_id": None}, {"conversationId": "", "conversation_id": None}, None),
    ({"conversation_id": " \t"}, {"conversationId": "", "conversation_id": " "}, None),
    ({"conversation_id": "JAVA/opaque-中文"}, {}, "JAVA/opaque-中文"),
    ({}, {"conversationId": "(\\existing-id\\\\)"}, "(\\existing-id\\\\)"),
    ({}, {"conversation_id": "  unchanged  "}, "  unchanged  "),
    ({"conversation_id": "same-id"},
     {"conversationId": "same-id", "conversation_id": "same-id"}, "same-id"),
])
def test_two_turn_inquiry_continues_history_and_sends_order_id_with_tenor(
    monkeypatch: pytest.MonkeyPatch,
    inquiry_workflow: tuple[TestClient, list[tuple[str, dict[str, Any]]]],
    top: dict[str, Any], aliases: dict[str, Any], expected_id: str | None,
) -> None:
    client, calls = inquiry_workflow
    intent_llm = _patch_llm(
        monkeypatch, "app.subgraphs.option.intent.get_qwen_structured",
        OptionIntentOutput, [{"type": "new_inquiry"}, {"type": "new_inquiry"}],
    )
    extract_llm = _patch_llm(
        monkeypatch, "app.subgraphs.option.extract_inquiry.get_qwen_thinking",
        OptionInquiryParams, [
            {"orderList": [{"stockCode": "300773.SZ", "optionType": "欧式看涨",
                            "strikePercentage": 80}]},
            {"orderList": [{"orderId": "Q-20260907-000001", "tenor": "1M"}]},
        ],
    )
    first = client.post("/v1/workflows/run", json={
        **top, "inputs": {"raw_content": FIRST_MESSAGE, "message_id": 1,
                          "room_id": "test-room", **aliases}, "user": "stable-user",
    })
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "succeeded"
    conversation_id = first.json()["conversationId"]
    if expected_id is None:
        assert str(UUID(conversation_id)) == conversation_id
        assert UUID(conversation_id).version == 4
    else:
        assert conversation_id == expected_id
    assert first.json()["answer"] == INQUIRY_CARD
    config = {"configurable": {"thread_id": conversation_id}}
    graph = client.app.state.main_graph
    first_state = graph.get_state(config).values
    assert first_state["conversation_id"] == conversation_id
    assert [(msg.role, msg.content) for msg in first_state["history_messages"]] == [
        ("user", FIRST_MESSAGE), ("assistant", INQUIRY_CARD),
    ]

    second = client.post("/v1/workflows/run", json={
        "conversation_id": conversation_id,
        "inputs": {"raw_content": "1M", "quote_content": first.json()["answer"],
                   "message_id": 2, "room_id": "test-room"}, "user": "stable-user",
    })
    assert second.status_code == 200, second.text
    assert second.json()["data"]["status"] == "succeeded"
    assert second.json()["conversationId"] == conversation_id
    assert second.json()["answer"] == UPDATED_CARD
    assert second.json()["data"]["outputs"]["reply_text"] == UPDATED_CARD
    assert [name for name, _ in calls] == ["operate", "set-intent", "operate", "set-intent"]
    assert all(payload["conversationId"] == conversation_id for _, payload in calls)
    assert calls[0][1]["orderList"] == [{
        "stockCode": "300773.SZ", "optionType": "欧式看涨", "strikePercentage": 80,
    }]
    assert calls[2][1]["type"] == "new_inquiry"
    assert calls[2][1]["quoteContent"] == INQUIRY_CARD
    # 仅传原单号与本轮新增期限，缺省参数交 Java 合并。
    assert calls[2][1]["orderList"] == [{"orderId": "Q-20260907-000001", "tenor": "1M"}]
    for _, payload in (calls[1], calls[3]):
        assert payload["intent"] == "new_inquiry"
        assert payload["productType"] == 0

    for invoke in (intent_llm, extract_llm):
        second_user_message = invoke.call_args_list[1].args[0][1][1]
        # 首轮原话不在引用卡片中；此断言证明历史由 checkpoint 续接到 LLM。
        assert FIRST_MESSAGE in second_user_message
        assert f"assistant: {INQUIRY_CARD}" in second_user_message
    second_state = graph.get_state(config).values
    assert second_state["conversation_id"] == conversation_id
    assert [(msg.role, msg.content) for msg in second_state["history_messages"]] == [
        ("user", FIRST_MESSAGE), ("assistant", INQUIRY_CARD),
        ("user", "1M"), ("assistant", UPDATED_CARD),
    ]


def test_order_extraction_preserves_tenor_for_backend_intent_correction(
    monkeypatch: pytest.MonkeyPatch,
    inquiry_workflow: tuple[TestClient, list[tuple[str, dict[str, Any]]]],
) -> None:
    client, calls = inquiry_workflow
    _patch_llm(monkeypatch, "app.subgraphs.option.intent.get_qwen_structured",
               OptionIntentOutput, [{"type": "place_order_from_quote"}])
    _patch_llm(monkeypatch, "app.subgraphs.option.extract_place.get_qwen_thinking",
               OptionPlaceParams,
               [{"orderList": [{"orderId": "Q-20260907-000001", "tenor": "1M"}]}])
    response = client.post("/v1/workflows/run", json={
        "conversation_id": "backend-corrects-intent",
        "inputs": {"raw_content": "1M", "quote_content": INQUIRY_CARD,
                   "message_id": 2, "room_id": "test-room"}, "user": "stable-user",
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    assert calls[0][1]["type"] == "place_order_from_quote"
    assert calls[0][1]["orderList"] == [{"orderId": "Q-20260907-000001", "tenor": "1M"}]
    assert response.json()["answer"] == UPDATED_CARD


@pytest.mark.parametrize("product,raw", [
    ("option", "期权查订单"), ("swap", "互换查订单"),
    ("option_close", "查询 CO-20260907-00000001"),
])
def test_business_subgraphs_do_not_duplicate_checkpoint_history(
    monkeypatch: pytest.MonkeyPatch,
    inquiry_workflow: tuple[TestClient, list[tuple[str, dict[str, Any]]]],
    product: str, raw: str,
) -> None:
    from app.subgraphs.close.models import CloseIntentOutput, QueryStatusParams
    from app.subgraphs.option.models import OptionQueryParams
    from app.subgraphs.swap.models import SwapIntentOutput

    cases = {
        "option": ("option", OptionIntentOutput, "query_order_status",
                   "extract_query", OptionQueryParams, "get_qwen_structured"),
        "swap": ("swap", SwapIntentOutput, "query_order_status",
                 "query_order", None, "get_qwen_thinking"),
        "option_close": ("close", CloseIntentOutput, "close_order_order_query",
                         "query_status", QueryStatusParams, "get_qwen_thinking"),
    }
    category, intent_schema, intent, extract_node, extract_schema, intent_factory = cases[product]
    _patch_llm(monkeypatch, f"app.subgraphs.{category}.intent.{intent_factory}",
               intent_schema, [{"type": intent}] * 3)
    if extract_schema is not None:
        _patch_llm(monkeypatch, f"app.subgraphs.{category}.{extract_node}.get_qwen_thinking",
                   extract_schema, [{}] * 3)
    client, calls = inquiry_workflow
    expected_history = []
    for message_id in range(1, 4):
        response = client.post("/v1/workflows/run", json={
            "conversation_id": "history-session",
            "inputs": {"raw_content": raw, "message_id": message_id, "room_id": "test-room"},
            "user": "stable-user",
        })
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "succeeded"
        assert response.json()["data"]["outputs"]["product_type"] == product
        expected_history.extend([("user", raw), ("assistant", response.json()["answer"])])
        checkpoint = client.app.state.main_graph.get_state({
            "configurable": {"thread_id": "history-session"},
        })
        assert [(msg.role, msg.content) for msg in checkpoint.values["history_messages"]] == (
            expected_history
        )
    assert all(payload["conversationId"] == "history-session" for _, payload in calls)
