"""
GOATS Mock API Server
Simulates all 20 interfaces from api_spec.md.
Run: uvicorn mock_goats_api.server:app --reload --port 8080
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="GOATS Mock API", version="1.0")

HKT = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ok(data=None) -> dict:
    return {
        "errMsg": None,
        "errCode": {"code": 200, "chs": "成功", "eng": "success"},
        "data": data,
    }

def fail(msg: str = "请求失败", code: int = 400) -> dict:
    return {
        "errMsg": msg,
        "errCode": {"code": code, "chs": msg, "eng": "FAIL_REQUEST"},
        "data": None,
    }

def now() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")

def today() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# middleware: log requests, return error on _error query param
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_and_check_error(request: Request, call_next):
    # Allow error simulation via ?_error=1 or ?_error=true
    if request.query_params.get("_error") in ("1", "true"):
        return JSONResponse(fail("模拟错误", 400))
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["x-mock-latency-ms"] = f"{elapsed:.0f}"
    return response


# ===================================================================
# 场外期权 (11 interfaces)
# ===================================================================

# 1. 期权询价查询
@app.post("/api/internal/agent/get_option_rfq")
async def option_rfq_query():
    return ok({
        "chatType": "json",
        "chatResult": [
            {
                "id": 34743226,
                "productType": "EUROPEAN_VANILLA",
                "productSubtype": None,
                "windName": "阿特斯",
                "windCode": "688472.SH",
                "currency": "CNY",
                "callPut": "CALL",
                "tenor": "1M",
                "strike": 0.8,
                "participateRate": 1,
                "structure": None,
                "price": 0.206,
                "initialObservationDate": None,
                "knockOutPrice": None,
                "knockInPrice": None,
                "maximumLossLevel": None,
                "estimateMargin": None,
                "annualizedCouponRate": None,
                "stepDown": None,
                "insFamily": "EQUITY",
                "exchange": "SSE",
                "crossCurrencyType": None,
                "settlementCurrency": None,
                "balance": 500,
            }
        ],
    })


# 2. 场外期权下单
@app.post("/api/internal/agent/option_order")
async def option_order():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "status": "SUBMITTED",
        "submitTime": now(),
    })


# 3. 期权下单状态查询接口 [轮询]
@app.post("/api/internal/agent/option_order_status")
async def option_order_status():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "orderStatus": "FILLED",
        "filledQty": 100,
        "avgPrice": 18.5,
        "execAmount": 1850,
        "statusUpdateTime": now(),
    })


# 4. 期权下单结果查询接口
@app.post("/api/internal/agent/option_order_result")
async def option_order_result():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "orderStatus": "FILLED",
        "filledQty": 100,
        "avgPrice": 18.5,
        "execAmount": 1850,
        "currency": "HKD",
        "updatedDateTime": now(),
    })


# 5. 场外期权撤单
@app.post("/api/internal/agent/option_cancel")
async def option_cancel():
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


# 6. 场外期权撤单结果查询 [轮询]
@app.post("/api/internal/agent/option_cancel_result")
async def option_cancel_result():
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "cancelStatus": "CANCELLED",
        "cancelTime": now(),
    })


# 7. [期权] 可平仓合约列表查询接口
@app.post("/api/internal/agent/option/position")
async def option_position():
    return ok([
        {
            "keyCapAcctId": 14081,
            "keyOrderId": 1167917,
            "orderCode": f"11086{today().replace('-', '')}0012",
            "orderDate": today(),
            "entrustDate": today(),
            "entrustTime": now(),
            "keyCtptyId": 11086,
            "ctptyShortName": "11086测试短名",
            "ctptyLongName": "富力一202512031405",
            "nameAbbreviation": "11086",
            "windCode": "0700.HK",
            "insShtDesc": "腾讯控股",
            "keyInstrumentId": 81825,
            "price": None,
            "fixPrice": None,
            "quantity": 100,
            "orderDirection": "BUY",
            "priceType": "MarketOrder",
            "algorithmType": "TWAP",
            "povPercent": None,
            "maxVol": 1,
            "startTime": now(),
            "endTime": f"{today()} 20:10:00",
            "orderStatus": "WORKING",
            "filledQty": None,
            "avgPrice": None,
            "execAmount": None,
            "entrustAmount": 47120,
            "displayQty": None,
            "displayQtyUnit": None,
            "displayQtyVariance": None,
            "frequency": None,
            "currency": "HKD",
            "keyOtcspAuthUserId": "1688857550806294",
            "authUserName": "于文轩",
            "phoneNo": "00000000000",
            "tradeChannel": "GOATSAPI",
            "tradingModel": None,
            "businessRemark": None,
            "remark": "Max Vol仅支持输入1~99正整数;",
            "uniqueId": f"GOATSAPI:11086:{int(time.time())}",
            "canWithdraw": True,
            "updatedDateTime": now(),
            "fixPriceType": None,
            "serialNo": None,
            "createdDateTime": now(),
            "withdrawQty": 100,
            "exchangeMarket": "HKEX",
            "transactionType": "HK_STOCK",
            "eqRecallType": None,
            "keyPlanId": None,
            "ultraContractCode": None,
            "planCode": None,
            "premarket": False,
            "priceLimitType": None,
            "canReplace": False,
            "orderType": "BY_QTY",
            "notional": None,
            "notionalCurrency": None,
            "emsxSequenceNo": None,
            "cumulateUnmatchedQty": None,
            "enableLimitPrice": None,
            "subOrderQty": None,
            "priceDiffInTick": None,
            "triggerTimeIntervalSeconds": None,
            "cancelTimeIntervalSeconds": None,
            "maxCancelOrderTimes": None,
            "businessType": None,
            "async": None,
        }
    ])


# 8. 场外期权平仓
@app.post("/api/internal/agent/option_close_order")
async def option_close_order():
    return ok({
        "closeOrderId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "closeStatus": "SUBMITTED",
        "submitTime": now(),
    })


# 9. 期权平仓订单查询接口
@app.post("/api/internal/agent/option_close_order_query")
async def option_close_order_query():
    return ok([{
        "keyCapAcctId": 14081,
        "keyOrderId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "orderDate": today(),
        "entrustDate": today(),
        "entrustTime": now(),
        "keyCtptyId": 11086,
        "ctptyShortName": "11086测试短名",
        "ctptyLongName": "富力一202512031405",
        "windCode": "0700.HK",
        "insShtDesc": "腾讯控股",
        "quantity": 100,
        "orderDirection": "SELL",
        "priceType": "MarketOrder",
        "algorithmType": "TWAP",
        "orderStatus": "FILLED",
        "filledQty": 100,
        "avgPrice": 472.0,
        "execAmount": 47200,
        "currency": "HKD",
        "exchangeMarket": "HKEX",
        "transactionType": "HK_STOCK",
        "createdDateTime": now(),
        "updatedDateTime": now(),
    }])


# 10. 场外期权平仓订单撤单
@app.post("/api/internal/agent/option_close_cancel")
async def option_close_cancel():
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


# 11. 场外期权平仓撤单结果查询 [轮询]
@app.post("/api/internal/agent/option_close_cancel_result")
async def option_close_cancel_result():
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "cancelStatus": "CANCELLED",
        "cancelTime": now(),
    })


# ===================================================================
# 收益互换 (6 interfaces)
# ===================================================================

# 12. 收益互换下单
@app.post("/api/internal/agent/trs_order")
async def trs_order():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "status": "SUBMITTED",
        "submitTime": now(),
    })


# 13. 收益互换下单状态查询接口 [轮询]
@app.post("/api/internal/agent/trs_order_status")
async def trs_order_status():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "orderStatus": "FILLED",
        "filledQty": 10000,
        "avgPrice": 472.5,
        "execAmount": 4725000,
        "currency": "HKD",
        "statusUpdateTime": now(),
    })


# 14. 收益互换下单/撤单结果查询接口 [轮询]
@app.post("/api/internal/agent/trs_order_result")
async def trs_order_result():
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "orderStatus": "FILLED",
        "filledQty": 10000,
        "avgPrice": 472.5,
        "execAmount": 4725000,
        "currency": "HKD",
        "updatedDateTime": now(),
    })


# 15. 收益互换撤单
@app.post("/api/internal/agent/trs_cancel")
async def trs_cancel():
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


# 16. 收益互换改单
@app.post("/api/internal/agent/trs_replace")
async def trs_replace():
    return ok({
        "replaceId": int(time.time() * 1000),
        "originOrderCode": f"TRS{today().replace('-', '')}0001",
        "newOrderCode": f"TRS{today().replace('-', '')}0002",
        "replaceStatus": "SUBMITTED",
        "submitTime": now(),
    })


# 17. 收益互换改单状态查询接口 [轮询]
@app.post("/api/internal/agent/trs_replace_status")
async def trs_replace_status():
    return ok({
        "replaceId": int(time.time() * 1000),
        "originOrderCode": f"TRS{today().replace('-', '')}0001",
        "newOrderCode": f"TRS{today().replace('-', '')}0002",
        "replaceStatus": "ACCEPTED",
        "statusUpdateTime": now(),
    })


# ===================================================================
# 交易对手 (1 interface)
# ===================================================================

# 18. 企微群绑定交易对手查询
@app.get("/api/internal/agent/getCtptyListByChatRoomId")
async def get_ctpty_list(type: str = "TRS"):
    return ok([
        {
            "ctptyId": 10049,
            "shortName": "临沂阿凡提",
            "longName": "上海猎鲸志投资管理有限公司",
            "groupFlag": "N",
            "transactionTypeList": [
                "HK_STOCK", "US_STOCK", "JP_STOCK", "KR_STOCK",
                "CROSS_OTHER", "CROSS_FUTURE", "A_SHARE",
            ],
        },
        {
            "ctptyId": 10833,
            "shortName": "10833测试短名",
            "longName": "10833测试产品",
            "groupFlag": "N",
            "transactionTypeList": [
                "HK_STOCK", "US_STOCK", "JP_STOCK", "KR_STOCK",
                "CROSS_OTHER", "CROSS_FUTURE", "A_SHARE",
            ],
        },
        {
            "ctptyId": 11125,
            "shortName": "11125测试短名（张天琪专用）",
            "longName": "吕测试企业-Ukey",
            "groupFlag": "N",
            "transactionTypeList": [
                "HK_STOCK", "US_STOCK", "JP_STOCK", "KR_STOCK",
                "CROSS_OTHER", "CROSS_FUTURE", "A_SHARE",
            ],
        },
    ])


# ===================================================================
# 投管系统 (1 interface)
# ===================================================================

# 19. 互换交易时间配置查询
@app.get("/api/uniweb/rpa/trs/tradingHoursConfig")
async def trading_hours_config():
    return ok([
        {"transactionType": "SZ_HK_CONNECT", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
        {"transactionType": "SH_HK_CONNECT", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
        {"transactionType": "A_SHARE", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:00:00", "region": None, "exchangeList": None},
        {"transactionType": "HK_STOCK", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
        {"transactionType": "US_STOCK", "tradingHoursStart": f"{today()} 09:00:00", "tradingHoursEnd": f"{today()} 05:00:00", "region": None, "exchangeList": None, "premarketTradingHoursStart": f"{today()} 21:30:00"},
        {"transactionType": "CROSS_FUTURE", "tradingHoursStart": f"{today()} 09:00:00", "tradingHoursEnd": f"{today()} 22:30:00", "region": "ASIA_PACIFIC", "exchangeList": ["HKEX", "SGX", "OSE"]},
        {"transactionType": "CROSS_FUTURE", "tradingHoursStart": f"{today()} 09:00:00", "tradingHoursEnd": f"{today()} 05:00:00", "region": "EUROPE", "exchangeList": ["ICE_EU", "LME", "EUREX"]},
        {"transactionType": "CROSS_FUTURE", "tradingHoursStart": f"{today()} 09:00:00", "tradingHoursEnd": f"{today()} 05:00:00", "region": "AMERICA", "exchangeList": ["CBOT", "CME", "COMEX", "NYMEX", "ICE", "NYBOT"]},
        {"transactionType": "JP_STOCK", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
        {"transactionType": "KR_STOCK", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
        {"transactionType": "CROSS_OTHER", "tradingHoursStart": f"{today()} 08:30:00", "tradingHoursEnd": f"{today()} 20:10:00", "region": None, "exchangeList": None},
    ])


# ===================================================================
# DIFY (1 interface)
# ===================================================================

# 20. 大模型 rerank 标的列表
@app.post("/v1/workflows/run")
async def dify_rerank():
    return {
        "task_id": "556a6022-7a4d-4e43-be8c-f12136e769b9",
        "workflow_run_id": "f44f69db-ad29-431b-a985-e8983c9e2ea8",
        "data": {
            "id": "f44f69db-ad29-431b-a985-e8983c9e2ea8",
            "workflow_id": "9acd5dee-a1a8-4b7d-8eb4-2d69fea19e2e",
            "status": "succeeded",
            "outputs": {"result": ["0200.HK"]},
            "error": None,
            "elapsed_time": 2.783889,
            "total_tokens": 1999,
            "total_steps": 6,
            "created_at": 1777535594,
            "finished_at": 1777535597,
        },
    }


# ===================================================================
# 后端业务 API Mock（OTC Backend，6 个接口）
# 响应格式：{"code": 0, "data": ..., "msg": "success"}
# 对应 app/tools/otc_backend.py 的 OtcBackendClient
# ===================================================================

def backend_ok(data=None):
    """后端统一成功响应。"""
    return {"code": 0, "data": data, "msg": "success"}


def backend_fail(code: int = 400, msg: str = "业务错误"):
    """后端统一错误响应。"""
    return {"code": code, "data": None, "msg": msg}


# 1. 互换订单操作（下单/撤单/改单/确认/查询）
@app.post("/admin-api/swap-order/operate")
async def swap_order_operate(request: Request):
    body = await request.json() if await request.body() else {}
    type_ = body.get("type", "unknown")
    return backend_ok(f"[mock] 互换{type_}操作已受理，订单号 TRS-{today().replace('-', '')}-0001")


# 2. 期权/平仓操作（询价/下单/撤单/持仓查询）
@app.post("/admin-api/financial-orders/operate")
async def financial_orders_operate(request: Request):
    body = await request.json() if await request.body() else {}
    type_ = body.get("type", "unknown")
    return backend_ok(f"[mock] 期权平仓{type_}操作已受理，单号 OPT-{today().replace('-', '')}-0001")


# 3. 交易对手列表
@app.get("/admin-api/counterparty/info/list")
async def counterparty_info_list():
    return backend_ok([
        {
            "id": 10049,
            "shortName": "临沂阿凡提",
            "longName": "上海猎鲸志投资管理有限公司",
            "groupFlag": "N",
        },
        {
            "id": 10833,
            "shortName": "10833测试",
            "longName": "10833测试产品",
            "groupFlag": "N",
        },
        {
            "id": 11125,
            "shortName": "11125测试",
            "longName": "吕测试企业-Ukey",
            "groupFlag": "N",
        },
    ])


# 4. 会话历史订单
@app.post("/admin-api/swap-order/get-conversation-orders")
async def get_conversation_orders():
    return backend_ok([
        {
            "orderId": f"TRS-{today().replace('-', '')}-0001",
            "windCode": "0700.HK",
            "insShtDesc": "腾讯控股",
            "quantity": 1000,
            "direction": "BUY",
            "status": "FILLED",
            "createTime": now(),
        },
    ])


# 5. Bot 名称列表（返回 JSON 字符串，与真实后端一致）
@app.post("/admin-api/business/config/bot/name/list")
async def bot_name_list():
    import json as _json
    return backend_ok(_json.dumps(["otc-agent", "交易助手", "OTC小助手"]))


# 6. 意图审计写入（无返回值，只需 code=0）
@app.post("/admin-api/openapi/xbot/message/set-intent")
async def set_intent():
    return backend_ok(None)


# ===================================================================
# health check + API list
# ===================================================================

@app.get("/")
async def root():
    routes = []
    for r in app.routes:
        if hasattr(r, "path") and hasattr(r, "methods"):
            routes.append(f"{r.methods} {r.path}")
    return {"service": "GOATS Mock API", "endpoints": len(routes), "routes": routes}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099)
