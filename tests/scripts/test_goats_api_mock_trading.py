"""本地模拟交易的 GOATS 契约、状态流转及身份隔离。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scripts.goats_api_mock.server import create_app

BASE = "/api/internal/agent/option/order/close"
HEADERS = {"agentid": "mock-room@tl", "agentsubid": "mock-user"}
ORDER = {"contractCode": "OPT-AAAA1", "notionalDelta": 1_000_000, "algoType": "LIMIT", "price": 10}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as instance:
        yield instance


def place(client: TestClient, **overrides: object) -> int:
    response = client.post(BASE, headers=HEADERS, json={**ORDER, **overrides})
    assert response.status_code == 200
    result = response.json()
    assert result["errCode"]["code"] == 200, result
    return result["data"]["keyStockOrderId"]


def query(client: TestClient, headers: dict[str, str] = HEADERS, **payload: object) -> dict:
    response = client.post(BASE + "/query", headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()["errCode"]["code"] == 200
    return response.json()["data"]


def test_close_query_withdraw_and_result_lifecycle(client: TestClient) -> None:
    identifier = place(client)
    page = query(client, filter={"tradeDate": date.today().isoformat()}, pageNum=1, pageSize=0)
    assert page["total"] == page["pageSize"] == 1
    order = page["queryResults"][0]
    assert order["keyStockOrderId"] == identifier
    assert order["contractCode"] == "OPT-AAAA1"
    assert order["stockOrderStatus"] == "OTC_VERIFYING"
    assert order["notionalDelta"] == 1_000_000
    assert order["allowWithdraw"] is True
    assert order["goatsPositionQueryDto"]["contractCode"] == order["contractCode"]

    withdrawal = client.post(BASE + "/withdraw", headers=HEADERS, json={"keyStockOrderId": identifier})
    assert withdrawal.json()["errCode"]["code"] == 200
    code = withdrawal.json()["data"]["stockOrderCode"]
    assert code.startswith("MOCK-CANCEL-")
    repeated = client.post(BASE + "/withdraw", headers=HEADERS, json={"keyStockOrderId": identifier})
    assert repeated.json() == withdrawal.json()

    result = client.get(BASE + "/withdrawResult", headers=HEADERS, params={"stockOrderCode": code})
    assert result.json()["errCode"]["code"] == 200
    assert result.json()["data"]["completed"] is True
    assert result.json()["data"]["withdrawResult"] == "SUCCESS"
    assert result.json()["data"]["failureMsg"] is None
    order = query(client)["queryResults"][0]
    assert order["stockOrderStatus"] == "CANCELED"
    assert order["allowWithdraw"] is False
    assert order["dealNotional"] == 0


def test_orders_are_scoped_by_group_and_optional_user(client: TestClient) -> None:
    identifier = place(client)
    for headers in ({"agentid": "other-room@tl"}, {**HEADERS, "agentsubid": "other-user"}):
        assert query(client, headers)["total"] == 0
        reply = client.post(BASE + "/withdraw", headers=headers, json={"keyStockOrderId": identifier})
        assert reply.json()["errCode"]["code"] != 200
    assert query(client, {"agentid": HEADERS["agentid"]})["total"] == 1
    # 群级读取可省略用户；撤单是写操作，缺 agentsubid 不能撤掉他人的订单
    reply = client.post(BASE + "/withdraw", headers={"agentid": HEADERS["agentid"]},
                        json={"keyStockOrderId": identifier})
    assert reply.json()["errCode"]["code"] != 200
    assert query(client)["queryResults"][0]["stockOrderStatus"] == "OTC_VERIFYING"


def test_order_ids_are_unique_and_queries_support_filters_and_paging(client: TestClient) -> None:
    first, second = place(client), place(client)
    assert first != second
    page = query(client, filter={"contractCode": "OPT-AAAA1"}, pageNum=2, pageSize=1)
    assert page["total"] == 2
    assert [row["keyStockOrderId"] for row in page["queryResults"]] == [second]
    assert query(client, filter={"tradeDate": "1900-01-01"})["total"] == 0
    assert query(client, filter={"contractCode": "DOES_NOT_EXIST"})["total"] == 0


@pytest.mark.parametrize("overrides", [
    {"contractCode": "DOES_NOT_EXIST"}, {"notionalDelta": 100_000_000},
])
def test_invalid_business_order_returns_goats_failure(client: TestClient, overrides: dict) -> None:
    reply = client.post(BASE, headers=HEADERS, json={**ORDER, **overrides})
    assert reply.status_code == 200
    assert reply.json()["errCode"]["code"] != 200
    assert reply.json()["errMsg"] and reply.json()["data"] is None
    assert query(client)["total"] == 0


def test_unknown_withdrawal_result_is_not_success(client: TestClient) -> None:
    reply = client.get(BASE + "/withdrawResult", headers=HEADERS, params={"stockOrderCode": "unknown"})
    assert reply.json()["errCode"]["code"] != 200
    assert reply.json()["data"] is None


def test_fixed_positions_do_not_change_and_new_instance_has_no_orders(client: TestClient) -> None:
    endpoint = "/api/internal/agent/option/position"
    before = client.post(endpoint, headers=HEADERS, json={}).json()
    place(client)
    assert client.post(endpoint, headers=HEADERS, json={}).json() == before
    with TestClient(create_app()) as another:
        assert query(another)["total"] == 0
