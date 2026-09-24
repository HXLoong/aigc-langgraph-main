"""互换 Mock 的真实 Java wire 形态、状态流转和群/用户隔离。"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from scripts.goats_api_mock.server import create_app

BASE = "/api/internal/agent/trs/order"
HEADERS = {"agentid": "mock-room@tl", "agentsubid": "mock-user"}
ORDER = {"windCode": "600519.SH", "transactionType": "A_SHARE", "quantity": 100,
         "orderDirection": "BUY", "priceType": "LimitOrder", "price": 1,
         "orderType": "BY_QTY", "shortName": "测试对手"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as instance:
        yield instance


def submit(client: TestClient) -> int:
    response = client.post(BASE, headers=HEADERS, json=ORDER)
    assert response.status_code == 200
    value = response.json()
    assert value["errCode"]["code"] == 200
    assert value["data"]["result"] is True and value["data"]["async"] is True
    identifier = value["data"]["keyOrderId"]
    assert 0 < identifier < 2**31
    return identifier


def query(client: TestClient, headers: dict | None = None) -> list[dict]:
    # Java 当前发 POST 空 body 查询本群结果。
    response = client.post(BASE + "/query", headers=headers or HEADERS)
    assert response.status_code == 200
    return response.json()["data"]


def test_swap_submit_approval_query_and_cancel_lifecycle(client: TestClient):
    identifier = submit(client)
    approval = client.post(BASE + "/status", headers=HEADERS,
                           json=[{"keyOrderId": identifier}]).json()["data"][0]
    assert approval["completed"] is True and approval["success"] is True
    assert approval["keyStockOrderId"] == identifier
    row = query(client)[0]
    assert row["keyOrderId"] == identifier and row["windCode"] == ORDER["windCode"]
    assert row["orderStatus"] == "NEW" and row["canWithdraw"] is True
    assert row["filledQty"] == 0
    withdrawal = client.post(BASE + "/withdraw", headers=HEADERS, json={"orderList": [identifier]})
    assert withdrawal.json()["data"] == [{"keyOrderId": identifier, "result": True, "msg": None}]
    assert client.post(BASE + "/withdraw", headers=HEADERS,
                       json={"orderList": [identifier]}).json() == withdrawal.json()
    row = query(client)[0]
    assert row["orderStatus"] == "CANCELED" and row["canWithdraw"] is False
    assert row["withdrawQty"] == 100 and row["filledQty"] == 0


@pytest.mark.parametrize("headers", [
    {"agentid": "other-room", "agentsubid": "mock-user"},
    {"agentid": "mock-room@tl", "agentsubid": "other-user"},
])
def test_swap_cross_identity_cannot_read_or_cancel(client: TestClient, headers: dict):
    identifier = submit(client)
    assert query(client, headers) == []
    response = client.post(BASE + "/withdraw", headers=headers, json={"orderList": [identifier]})
    assert response.json()["errCode"]["code"] != 200
    assert query(client)[0]["orderStatus"] == "NEW"
    assert len(query(client, {"agentid": HEADERS["agentid"]})) == 1


def test_swap_unknown_batch_member_cannot_partially_cancel(client: TestClient):
    identifier = submit(client)
    response = client.post(BASE + "/withdraw", headers=HEADERS,
                           json={"orderList": [identifier, identifier + 100]})
    assert response.json()["errCode"]["code"] != 200
    assert query(client)[0]["orderStatus"] == "NEW"
    result = client.post(BASE + "/status", headers=HEADERS,
                         json=[{"keyOrderId": identifier + 100}])
    assert result.json()["errCode"]["code"] != 200


@pytest.mark.parametrize("quantity", [0, -1])
def test_swap_invalid_quantity_does_not_create_order(client: TestClient, quantity: int):
    assert client.post(BASE, headers=HEADERS, json={**ORDER, "quantity": quantity}).status_code == 422
    assert query(client) == []


def test_swap_limit_price_is_required(client: TestClient):
    value = {key: val for key, val in ORDER.items() if key != "price"}
    response = client.post(BASE, headers=HEADERS, json=value)
    assert response.status_code == 200
    assert response.json()["errCode"]["code"] != 200
    assert query(client) == []


def test_swap_amount_preserves_notional_without_inventing_quantity(client: TestClient):
    value = {key: val for key, val in ORDER.items() if key != "quantity"}
    value.update(notional=2000000, notionalCurrency="CNY", orderType="BY_AMOUNT")
    response = client.post(BASE, headers=HEADERS, json=value)
    assert response.status_code == 200
    assert response.json()["errCode"]["code"] == 200
    row = query(client)[0]
    assert row["notional"] == 2000000 and row.get("quantity") is None
