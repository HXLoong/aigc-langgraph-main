"""Java 开仓契约：申请编号、审核编号、查询结果及撤单终态。"""
from fastapi.testclient import TestClient

from scripts.goats_api_mock.server import create_app

BASE = "/api/internal/agent/option/order"
HEADERS = {"agentid": "test-room", "agentsubid": "test-user"}
ORDER = {
    "id": 12345, "contractType": "EUROPEAN_VANILLA", "direction": "CALL",
    "tradeDirection": "BUY", "quotationOrderType": "QUOTATION_FILE",
    "openPositionType": "MARKET_PRICE", "collateralNotional": 2_000_000,
    "shortName": "测试对手",
}


def test_open_approval_cancel_and_terminal_result():
    with TestClient(create_app()) as client:
        placed = client.post(BASE, headers=HEADERS, json=ORDER)
        assert placed.status_code == 200
        placing_id = placed.json()["data"]
        assert isinstance(placing_id, str)
        status = client.get(BASE + "/status", headers=HEADERS, params={"orderId": placing_id})
        assert status.json()["errCode"]["code"] == 200
        approved = status.json()["data"]
        assert approved["completed"] is approved["success"] is True
        identifier = approved["keyStockOrderId"]
        assert 0 < identifier <= 2**31 - 1  # Java 接收 Integer

        def row():
            response = client.post(BASE + "/query", headers=HEADERS, json={
                "filter": {"contractType": "EUROPEAN_VANILLA", "keyStockOrderId": identifier},
                "pageNum": 1, "pageSize": 100,
            })
            page = response.json()["data"]
            assert page["total"] == page["pageSize"] == 1
            return page["queryResults"][0]

        assert row()["trdGoatsOptionOrder"]["orderStatus"] == "TOTRADE_PENDING"
        assert row()["trdGoatsOptionStructure"]["initialNotional"] == 2_000_000
        withdrawn = client.post(BASE + "/withdraw", headers=HEADERS,
                                json={"keyStockOrderId": identifier})
        assert withdrawn.json()["errCode"]["code"] == 200
        receipt = withdrawn.json()["data"]
        assert receipt["completed"] is False
        assert row()["trdGoatsOptionOrder"]["orderStatus"] == "PENDING_CANCEL"
        result = client.get(BASE + "/withdrawResult", headers=HEADERS,
                            params={"stockOrderCode": receipt["stockOrderCode"]}).json()
        assert result["data"]["completed"] is True
        assert result["data"]["withdrawResult"] == "SUCCESS"
        assert row()["trdGoatsOptionOrder"]["orderStatus"] == "CANCELLED"
        assert row()["trdGoatsOptionOrder"]["dealNotional"] == 0
        assert client.post(BASE + "/withdraw", headers=HEADERS,
                           json={"keyStockOrderId": identifier}).json() == withdrawn.json()


def test_open_unknown_and_other_owners_cannot_succeed():
    with TestClient(create_app()) as client:
        response = client.post(BASE, headers=HEADERS, json=ORDER)
        assert response.status_code == 200
        placing_id = response.json()["data"]
        identifier = client.get(BASE + "/status", headers=HEADERS,
                                params={"orderId": placing_id}).json()["data"]["keyStockOrderId"]
        for headers in ({"agentid": "other-room"}, {**HEADERS, "agentsubid": "other-user"}):
            assert client.get(BASE + "/status", headers=headers,
                              params={"orderId": placing_id}).json()["errCode"]["code"] != 200
            assert client.post(BASE + "/query", headers=headers, json={}).json()["data"]["total"] == 0
            assert client.post(BASE + "/withdraw", headers=headers,
                               json={"keyStockOrderId": identifier}).json()["errCode"]["code"] != 200
        assert client.post(BASE + "/query", headers={"agentid": HEADERS["agentid"]},
                           json={}).json()["data"]["total"] == 1
        # 撤单是写操作：缺 agentsubid 的群级请求不能撤掉下单用户的订单
        assert client.post(BASE + "/withdraw", headers={"agentid": HEADERS["agentid"]},
                           json={"keyStockOrderId": identifier}).json()["errCode"]["code"] != 200
        assert client.get(BASE + "/withdrawResult", headers=HEADERS,
                          params={"stockOrderCode": "missing"}).json()["errCode"]["code"] != 200
        assert client.post(BASE, headers=HEADERS,
                           json={**ORDER, "collateralNotional": -1}).status_code == 422
