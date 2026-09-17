"""GOATS Mock API Server.

挂载两套接口：
- **GOATS 外部接口**（`/api/internal/agent/*` + `/api/uniweb/...`）— 模拟 GOATS 对客机器人 20 个端点
- **Java 后端接口**（`/admin-api/...`）— 模拟 yudao 后端 9 个端点（按真实 DTO 校验）
- **Dify 工作流回调**（`/v1/workflows/run`）— 模拟 Dify rerank

Run:
    uvicorn mock_api.server:app --reload --port 8099
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from mock_api.backend import router as backend_router

app = FastAPI(title="GOATS + OTC Backend Mock API", version="2.0")

HKT = timezone(timedelta(hours=8))


# ============================================================
# GOATS 响应辅助（保持原格式 {errMsg, errCode, data}）
# ============================================================


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


# ============================================================
# 中间件：请求日志 + _error 模拟
# ============================================================


@app.middleware("http")
async def log_and_check_error(request: Request, call_next):
    if request.query_params.get("_error") in ("1", "true"):
        return JSONResponse(fail("模拟错误", 400))
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["x-mock-latency-ms"] = f"{elapsed:.0f}"
    return response


# ============================================================
# 后端业务接口（/admin-api/*）— 拆模块化，按真实 Java DTO 校验
# ============================================================

app.include_router(backend_router)


# ============================================================
# 场外期权 GOATS 接口（11 个）
# ============================================================


@app.post("/api/internal/agent/get_option_rfq")
async def option_rfq_query():
    """1. 期权询价查询（GOATS 外部）。"""
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


@app.post("/api/internal/agent/option_rfq_instrument_parser")
@app.post("/internal/agent/option_rfq_instrument_parser")
async def option_rfq_instrument_parser(request: Request):
    """1b. 快速询价指令解析（DSL v2 fast_query 前置分支，2026-08 新增）。

    返回真实端点的 {errCode, errMsg, data} 信封，客户端在业务成功后
    解包 data 作为 optionRfq。双前缀挂载保留对旧测试地址的兼容。
    """
    body = await request.json()
    chat = body.get("chatInstrument", "")
    data = {
        "chatType": "json",
        "chatInstrument": chat,
        "productType": "EUROPEAN_VANILLA",
        "productSubtypeList": [],
        "fuzzyCodeList": ["600519.SH"],
        "tenor": ["1M"],
        "strike": ["100"],
        "participateRate": [],
        "knockInPrice": [],
        "knockOutPrice": [],
        "estimateMargin": [],
    }
    return {"errCode": {"code": 200}, "errMsg": "", "data": data}


@app.post("/api/internal/agent/instruction/query")
@app.post("/internal/agent/instruction/query")
async def instruction_query(request: Request):
    """1c. 存量兼容交易查询（DSL v2 fast_query 前置分支，2026-08 新增）。

    返回查询 JSON；client 侧 errMsg 恒为静默哨兵，
    响应体只作为 api_data_result_obj 透传。
    """
    body = await request.json()
    return {
        "chatType": "json",
        "chatInstruction": body.get("chatInstruction", ""),
        "chatResult": [
            {
                "orderId": "Q-20260829-0001",
                "windCode": "600519.SH",
                "windName": "贵州茅台",
                "status": "CONFIRMED",
                "balance": 500,
            }
        ],
    }


@app.post("/api/internal/agent/option_order")
async def option_order():
    """2. 期权下单（GOATS）。"""
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "status": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/option_order_status")
async def option_order_status():
    """3. 期权下单状态查询（轮询）。"""
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "orderStatus": "FILLED",
        "filledQty": 100,
        "avgPrice": 18.5,
        "execAmount": 1850,
        "statusUpdateTime": now(),
    })


@app.post("/api/internal/agent/option_order_result")
async def option_order_result():
    """4. 期权下单结果查询。"""
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


@app.post("/api/internal/agent/option_cancel")
async def option_cancel():
    """5. 期权撤单。"""
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/option_cancel_result")
async def option_cancel_result():
    """6. 期权撤单结果查询（轮询）。"""
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"OPT{today().replace('-', '')}0001",
        "cancelStatus": "CANCELLED",
        "cancelTime": now(),
    })


@app.post("/api/internal/agent/option/position")
async def option_position():
    """7. 可平仓合约列表。"""
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


@app.post("/api/internal/agent/option_close_order")
async def option_close_order():
    """8. 期权平仓。"""
    return ok({
        "closeOrderId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "closeStatus": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/option_close_order_query")
async def option_close_order_query():
    """9. 期权平仓订单查询。"""
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


@app.post("/api/internal/agent/option_close_cancel")
async def option_close_cancel():
    """10. 期权平仓订单撤单。"""
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/option_close_cancel_result")
async def option_close_cancel_result():
    """11. 期权平仓撤单结果查询（轮询）。"""
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"CLS{today().replace('-', '')}0001",
        "cancelStatus": "CANCELLED",
        "cancelTime": now(),
    })


# ============================================================
# 收益互换 GOATS 接口（6 个）
# ============================================================


@app.post("/api/internal/agent/trs_order")
async def trs_order():
    """12. 收益互换下单。"""
    return ok({
        "orderId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "status": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/trs_order_status")
async def trs_order_status():
    """13. 收益互换下单状态查询（轮询）。"""
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


@app.post("/api/internal/agent/trs_order_result")
async def trs_order_result():
    """14. 收益互换下单/撤单结果查询。"""
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


@app.post("/api/internal/agent/trs_cancel")
async def trs_cancel():
    """15. 收益互换撤单。"""
    return ok({
        "cancelId": int(time.time() * 1000),
        "orderCode": f"TRS{today().replace('-', '')}0001",
        "cancelStatus": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/trs_replace")
async def trs_replace():
    """16. 收益互换改单。"""
    return ok({
        "replaceId": int(time.time() * 1000),
        "originOrderCode": f"TRS{today().replace('-', '')}0001",
        "newOrderCode": f"TRS{today().replace('-', '')}0002",
        "replaceStatus": "SUBMITTED",
        "submitTime": now(),
    })


@app.post("/api/internal/agent/trs_replace_status")
async def trs_replace_status():
    """17. 收益互换改单状态查询（轮询）。"""
    return ok({
        "replaceId": int(time.time() * 1000),
        "originOrderCode": f"TRS{today().replace('-', '')}0001",
        "newOrderCode": f"TRS{today().replace('-', '')}0002",
        "replaceStatus": "ACCEPTED",
        "statusUpdateTime": now(),
    })


# ============================================================
# 交易对手（1 个）
# ============================================================


@app.get("/api/internal/agent/getCtptyListByChatRoomId")
async def get_ctpty_list(type: str = Query("TRS")):
    """18. 企微群绑定交易对手查询。"""
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


# ============================================================
# 投管系统（1 个）
# ============================================================


@app.get("/api/uniweb/rpa/trs/tradingHoursConfig")
async def trading_hours_config():
    """19. 互换交易时间配置查询。"""
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

# ============================================================
# 健康检查 + 路由清单
# ============================================================


@app.get("/")
async def root():
    routes = []
    for r in app.routes:
        if hasattr(r, "path") and hasattr(r, "methods"):
            routes.append(f"{sorted(r.methods)} {r.path}")
    return {
        "service": "GOATS + OTC Backend Mock API",
        "version": app.version,
        "endpoints": len(routes),
        "routes": sorted(routes),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8099)
