"""真实产品图必须在 Java 提交前经过清洗，原始证据不被覆盖。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.joint_support import instruction_data


@pytest.mark.parametrize("product,intent,order,field", [
    ("option", "new_inquiry", {"stockCode": "茅台", "notionalAmount": "100万"}, "notionalAmount"),
    ("swap", "place_order_request", {"placeOrderWindCode": "茅台", "placeOrderNotional": "100万"}, "placeOrderNotional"),
    ("close", "close_order_request", {"internalTradeId": "OPT-1", "closeOrderNotionalDelta": "100万"}, "closeOrderNotionalDelta"),
])
async def test_product_graph_cleans_request_and_keeps_raw_ledger(monkeypatch, product, intent, order, field) -> None:
    """仅替换 Client Protocol；参数准备、字段锁、清洗与图路由全部真实执行。"""
    from importlib import import_module

    backend = import_module(f"app.subgraphs.{product}.backend")
    graph_module = import_module(f"app.subgraphs.{product}.graph")
    requests = []

    async def operate(request):
        requests.append(request.model_dump(mode="json", exclude_none=True))
        return {"code": 0, "data": "Java card", "msg": ""}

    client_name = "SwapClientHttpx" if product == "swap" else "OptionClientHttpx"
    monkeypatch.setattr(backend, client_name, lambda: SimpleNamespace(operate=AsyncMock(side_effect=operate)))
    raw = "期权互换平仓 茅台 OPT-1 100万"
    product_type = "option_close" if product == "close" else product
    result = await getattr(graph_module, f"build_{product}_graph")().ainvoke({
        "raw_text": raw, "product_type": product_type, "parsed_instruction": instruction_data(product_type, intent, raw, orders=[order]),
        "conversation_id": "c", "message_id": 1, "room_id": "r", "user_id": "u",
    })
    assert result.get("error") is None
    assert len(requests) == 1
    body = requests[0]
    sent = body["closeOrderReqVO"]["closeOrderList"] if product == "close" else body["orderList"]
    assert len(sent) == 1 and field not in sent[0]
    assert result["backend_request"] == body
    assert any(record.value == "100万" for record in result["field_records"].values())
    assert any(record["action"] == "omit" and record["path"].endswith(field) for record in result["cleaning_records"])
    nodes = [entry.node for entry in result["trace"]]
    assert nodes.index(f"{product}_clean_request") < nodes.index(f"{product}_submit")


@pytest.mark.parametrize("product,expected_type", [("option", None), ("swap", None), ("close", "close_order_request")])
async def test_json_fallback_reaches_java_without_unknown_intent(monkeypatch, product, expected_type) -> None:
    """字符串入口损坏时仍调用 Java，并核对显式 null 和平仓外部意图。"""
    from importlib import import_module

    backend = import_module(f"app.subgraphs.{product}.backend")
    requests = []

    async def operate(request):
        requests.append(request.model_dump(mode="json", exclude_none=True))
        return {"code": 500, "msg": "Java rejected empty request", "data": None}

    name = "SwapClientHttpx" if product == "swap" else "OptionClientHttpx"
    monkeypatch.setattr(backend, name, lambda: SimpleNamespace(operate=operate))
    state = {"conversation_id": "c", "message_id": 1, "raw_text": "test", "room_id": "r", "user_id": "u",
             "pending_backend_request": {"product": product, "payload": "{broken", "intent": "close_order_request"}}
    clean = await getattr(backend, f"{product}_clean_request")(state)
    result = await getattr(backend, f"{product}_submit")({**state, **clean})
    assert result.get("error") is None
    assert len(requests) == 1 and requests[0]["type"] == expected_type
    assert requests[0]["orderList"] == []
    if product == "close":
        assert requests[0]["closeOrderReqVO"] == {} and requests[0]["optionRfq"] == {}
    elif product == "option":
        assert requests[0]["operate"] is None


async def test_standalone_cleaning_cannot_redirect_locked_identity() -> None:
    """清洗节点独立回放也必须保留字段锁，不能给另一个订单生成可提交请求。"""
    from app.extraction.fields import FieldRecord
    from app.node_execution.executor import NodeExecutor
    from app.node_execution.prepare import prepare_state
    from app.node_execution.registry import build_registry

    spec = next(item for item in build_registry() if item.name == "option_clean_request")
    state = {"pending_backend_request": {"product": "option", "intent": "confirm_order",
             "payload": {"type": "confirm_order", "orderList": [{"orderId": "Q-FOREIGN"}]}},
             "field_records": {"option/parse.orderList.0.orderId": FieldRecord(value="Q-SELECTED", source="user", locked=True)}}
    prepared = prepare_state(spec, state)
    output = await NodeExecutor([spec]).run("option", spec.name, prepared.state)
    assert output.get("error")
    assert not output.get("cleaned_backend_request")


@pytest.mark.parametrize("product", ["option", "swap", "close"])
async def test_dify_fallback_uses_real_http_serialization_and_error_reply(monkeypatch, product) -> None:
    """真实 Client → HTTP 替身核对 null 键、一次派发及 Dify HTTP 错误展示。"""
    import json
    from importlib import import_module

    import httpx

    from app.tools.receipts import SERVICE_UNAVAILABLE

    backend = import_module(f"app.subgraphs.{product}.backend")
    client_module = import_module(f"app.tools.{'swap' if product == 'swap' else 'option'}_client")
    cls_name = "SwapClientHttpx" if product == "swap" else "OptionClientHttpx"
    client_cls = getattr(client_module, cls_name)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"msg": "type required"})

    monkeypatch.setattr(backend, cls_name, lambda: client_cls(
        base_url="http://java.invalid", token="test", transport=httpx.MockTransport(respond), dry_run=False))
    state = {"conversation_id": "c", "message_id": 1, "raw_text": "test", "room_id": "r", "user_id": "u",
             "pending_backend_request": {"product": product, "payload": "{broken", "intent": "close_order_request"}}
    cleaned = await getattr(backend, f"{product}_clean_request")(state)
    result = await getattr(backend, f"{product}_submit")({**state, **cleaned})
    assert len(requests) == 1
    assert requests[0]["type"] == ("close_order_request" if product == "close" else None)
    assert result["reply_text"] == SERVICE_UNAVAILABLE
    assert result["backend_request"] == requests[0]
    assert result["trace"][0].llm_output["http_status"] == 400


async def test_node_execution_round_trip_preserves_decimal_digits(monkeypatch) -> None:
    """清洗结果经节点 API 序列化再提交，不能变成浮点数而丢失金额精度。"""
    from app.node_execution.executor import NodeExecutor
    from app.node_execution.registry import build_registry

    requests = []

    async def operate(self, request):
        requests.append(request.model_dump(mode="json", exclude_none=True))
        return {"code": 0, "data": "Java card"}

    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    amount = "9007199254740993.01"
    state = {"conversation_id": "c", "message_id": 1, "room_id": "r", "user_id": "u", "raw_text": amount,
             "pending_backend_request": {"product": "option", "intent": "new_inquiry",
                 "payload": {"type": "new_inquiry", "operate": "询价", "orderList": [{"notionalAmount": amount}]}}}
    executor = NodeExecutor(build_registry())
    cleaned = await executor.run("option", "option_clean_request", state)
    result = await executor.run("option", "option_submit", {**state, **cleaned})
    assert not result.get("error"), result
    assert requests[0]["orderList"][0]["notionalAmount"] == amount


async def test_java_string_business_values_are_not_python_enum_errors(monkeypatch) -> None:
    """Java 声明 String 的枚举语义交给 Java；Python 不能在清洗后把整次请求拦下。"""
    from app.subgraphs.swap import backend

    requests = []

    async def operate(request):
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 400, "msg": "Java: 方向无效"}

    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SimpleNamespace(operate=operate))
    result = await backend.call_swap_backend({"conversation_id": "c", "message_id": 1,
        "raw_text": "未知方向", "room_id": "r", "user_id": "u"},
        intent="place_order_request", order_list=[{"placeOrderOrderDirection": "UNKNOWN_DIRECTION"}])
    assert requests[0]["orderList"][0]["placeOrderOrderDirection"] == "UNKNOWN_DIRECTION"
    assert result["api_code"] == 400 and result["api_result"] == "Java: 方向无效"
