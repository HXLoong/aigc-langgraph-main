"""GOATS Mock API 全接口测试脚本。
用法：
    1. 先启动 mock：  uvicorn mock_goats_api.server:app --port 8099
    2. 再运行本脚本：python mock_goats_api/test_all_endpoints.py
    3. 指定端口：    python mock_goats_api/test_all_endpoints.py --port 8080
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import httpx

BASE = "http://localhost:8099"

HEADERS_OPTION = {
    "Content-Type": "application/json",
    "agenttype": "WECHAT",
    "agentid": "10955866372569317@tl",
    "agentsubid": "1688856778752437",
    "clientid": "TL_AGENT",
    "clientsecret": "tltest",
}

HEADER_COMMON = {
    "Content-Type": "application/json",
    "agenttype": "WECHAT",
    "agentid": "10821094351495088@tl",
    "agentsubid": "1688855175747584",
    "clientid": "TL_AGENT",
    "clientsecret": "tltest",
}


@dataclass
class Case:
    name: str
    method: str
    path: str
    headers: dict | None = None
    body: dict | None = None
    query: dict | None = None


CASES: list[Case] = [
    # ======================== 场外期权 ========================
    Case("期权询价查询", "POST", "/api/internal/agent/get_option_rfq", HEADERS_OPTION,
         {"chatType": "json", "chatInstrument": "快速询价：欧式看涨，688472.SH，100，6M",
          "productType": "EUROPEAN_VANILLA", "productSubtypeList": [],
          "fuzzyCodeList": ["688472.SH"], "tenor": [], "strike": [],
          "participateRate": [], "knockInPrice": [], "knockOutPrice": [], "estimateMargin": []}),
    Case("期权下单", "POST", "/api/internal/agent/option_order", HEADERS_OPTION,
         {"id": 34743226, "contractType": "EUROPEAN_VANILLA", "direction": "CALL",
          "tradeDirection": "BUY", "quotationOrderType": "QUOTATION_FILE",
          "openPositionType": "MARKET_PRICE", "collateralNotional": 1000000}),
    Case("期权下单状态查询(轮询)", "POST", "/api/internal/agent/option_order_status", HEADERS_OPTION,
         {"orderId": "1689eeab08334a348ebf91ceea13096c"}),
    Case("期权下单结果查询", "POST", "/api/internal/agent/option_order_result", HEADERS_OPTION,
         {"filter": {"keyStockOrderId": 973409, "contractType": "EUROPEAN_VANILLA"},
          "pageNum": 1, "pageSize": 100}),
    Case("期权撤单", "POST", "/api/internal/agent/option_cancel", HEADERS_OPTION,
         {"keyStockOrderId": 271473}),
    Case("期权撤单结果查询(轮询)", "POST", "/api/internal/agent/option_cancel_result", HEADERS_OPTION,
         {"stockOrderCode": "OPTG-WFJJ202509030002"}),
    Case("可平仓合约列表", "POST", "/api/internal/agent/option/position", HEADER_COMMON,
         {"filter": {"allowCloseOut": True}, "pageNum": 1, "pageSize": 15}),
    Case("期权平仓", "POST", "/api/internal/agent/option_close_order", HEADER_COMMON,
         {"notionalDelta": 10000, "algoType": "LIMIT", "price": 15.1,
          "contractCode": "OPTG-SZZSCF20250030"}),
    Case("期权平仓订单查询", "POST", "/api/internal/agent/option_close_order_query", HEADER_COMMON,
         {"filter": {"tradeDate": "2026-05-06"}, "pageNum": 1, "pageSize": 100}),
    Case("期权平仓撤单", "POST", "/api/internal/agent/option_close_cancel", HEADER_COMMON,
         {"keyStockOrderId": 1150076}),
    Case("期权平仓撤单结果查询(轮询)", "POST", "/api/internal/agent/option_close_cancel_result", HEADER_COMMON,
         {"stockOrderCode": "OPTG-SZZSCF202602040001"}),

    # ======================== 收益互换 ========================
    Case("互换下单", "POST", "/api/internal/agent/trs_order", HEADER_COMMON,
         {"transactionType": "US_STOCK", "orderType": "BY_QTY", "quantity": 200,
          "windCode": "TSLA.O", "price": 1, "priceType": "LimitOrder",
          "orderDirection": "BUY", "shortName": "测试短名"}),
    Case("互换下单状态查询(轮询)", "POST", "/api/internal/agent/trs_order_status", HEADER_COMMON,
         [{"keyOrderId": 972871, "transactionType": "HK_STOCK"}]),
    Case("互换下单/撤单结果查询(轮询)", "POST", "/api/internal/agent/trs_order_result", HEADER_COMMON,
         {"ultraContractCode": "CSC-CST-多空组合-0004"}),
    Case("互换撤单", "POST", "/api/internal/agent/trs_cancel", HEADER_COMMON,
         {"orderList": [972873]}),
    Case("互换改单", "POST", "/api/internal/agent/trs_replace", HEADER_COMMON,
         {"orderList": [{"keyOrderId": 972871, "priceType": "LimitOrder",
                         "quantity": 2300, "price": 19, "algorithmType": "TWAP",
                         "startTime": "2025-09-19 11:00:00", "endTime": "2025-09-19 14:00:00"}]}),
    Case("互换改单状态查询(轮询)", "POST", "/api/internal/agent/trs_replace_status", HEADER_COMMON,
         {"orderList": [973746]}),

    # ======================== 交易对手 ========================
    Case("企微群绑定交易对手查询", "GET", "/api/internal/agent/getCtptyListByChatRoomId",
         HEADER_COMMON, query={"type": "TRS"}),

    # ======================== 投管 ========================
    Case("互换交易时间配置查询", "GET", "/api/uniweb/rpa/trs/tradingHoursConfig", HEADER_COMMON),

    # ======================== Dify ========================
    Case("大模型rerank标的", "POST", "/v1/workflows/run",
         {"Content-Type": "application/json"},
         {"inputs": {"list": '[{"windCode":"0200.HK","insShtDesc":"新濠国际发展"}]',
                      "keyword": "0200.hk"},
          "user": "ai-trading-assistant", "response_mode": "blocking"}),

    # ======================== 错误模拟 ========================
    Case("模拟错误(_error=1)", "POST", "/api/internal/agent/trs_order?_error=1", HEADER_COMMON,
         {"transactionType": "HK_STOCK"}),
]


async def run_one(client: httpx.AsyncClient, case: Case, base: str) -> dict:
    url = f"{base}{case.path}"
    kwargs = {"headers": case.headers}
    if case.body is not None:
        kwargs["json"] = case.body
    if case.query is not None:
        kwargs["params"] = case.query

    match case.method:
        case "GET":
            resp = await client.get(url, **kwargs)
        case "POST":
            resp = await client.post(url, **kwargs)
        case _:
            raise ValueError(f"Unknown method: {case.method}")

    return {
        "name": case.name,
        "method": case.method,
        "path": case.path,
        "status": resp.status_code,
        "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
    }


async def main(port: int):
    base = f"http://localhost:{port}"
    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i, case in enumerate(CASES, 1):
            try:
                result = await run_one(client, case, base)
                status = result["status"]
                ok_flag = status == 200
                if ok_flag:
                    passed += 1
                else:
                    failed += 1

                marker = "OK" if ok_flag else "FAIL"
                body = result.get("body", "")
                err_code = ""
                if isinstance(body, dict):
                    ec = body.get("errCode", {})
                    if isinstance(ec, dict):
                        err_code = f" errCode={ec.get('code')}"
                print(f"[{i:02d}] {marker} {status}{err_code}  {result['method']} {result['path']}")
                if not ok_flag:
                    print(f"     Response: {json.dumps(body, ensure_ascii=False, default=str)[:200]}")
            except httpx.ConnectError:
                failed += 1
                print(f"[{i:02d}] FAIL 连接失败  {case.method} {case.path}")
                print(f"     请先启动 Mock 服务: uvicorn mock_goats_api.server:app --port {port}")
                break
            except Exception as e:
                failed += 1
                print(f"[{i:02d}] FAIL {type(e).__name__}: {e}  {case.method} {case.path}")

    print(f"\n{'='*50}")
    print(f"结果: {passed} passed, {failed} failed, {len(CASES)} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GOATS Mock API 全接口测试")
    parser.add_argument("--port", type=int, default=8099, help="Mock 服务端口 (默认 8099)")
    args = parser.parse_args()
    import asyncio
    asyncio.run(main(args.port))
