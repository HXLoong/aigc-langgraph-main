"""GOATS 全部 19 个业务接口连通性探针（手工脚本，不是 pytest 用例）。

逐接口探测，链式调用：下单→拿ID→撤单/改单/状态查询。
用法: python scripts/probe_goats/probe_all_endpoints.py [--confirm-write]
写类接口默认拒绝执行，见 _utils.post。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

from _utils import COM_AID, COM_SUB, OPT_AID, OPT_SUB, check, get, post  # noqa: F401


class Result:
    def __init__(self, name: str, method: str, path: str,
                 ok: bool, code: int | None, msg: str = "", detail: str = ""):
        self.name = name
        self.method = method
        self.path = path
        self.ok = ok
        self.code = code
        self.msg = msg
        self.detail = detail


def main():
    results: list[Result] = []

    print("=" * 70)
    print("GOATS 全接口连通性测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ==================== 01. 期权询价查询 ====================
    print("[01/19] 期权询价查询...", end=" ")
    d = post("/api/internal/agent/get_option_rfq",
             {"chatType": "json", "chatInstrument": "快速询价：欧式看涨，688472.SH，100，6M",
              "productType": "EUROPEAN_VANILLA", "productSubtypeList": [],
              "fuzzyCodeList": ["688472.SH"], "tenor": [], "strike": [],
              "participateRate": [], "knockInPrice": [], "knockOutPrice": [],
              "estimateMargin": []},
             OPT_AID, OPT_SUB)
    ok, code, msg = check(d)
    n = len(d.get("data", {}).get("chatResult", [])) if d.get("data") else 0
    results.append(Result("期权询价查询", "POST",
                          "/api/internal/agent/get_option_rfq",
                          ok, code, msg, f"返回{n}条询价"))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 02. 期权下单 ====================
    print("[02/19] 期权下单...", end=" ")
    d = post("/api/internal/agent/option/order",
             {"id": 37053781, "contractType": "EUROPEAN_VANILLA",
              "direction": "CALL", "tradeDirection": "BUY",
              "quotationOrderType": "QUOTATION_FILE",
              "openPositionType": "MARKET_PRICE", "collateralNotional": 1000000},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    opt_order_id = d.get("data") if d.get("data") else None
    detail = f"orderId={opt_order_id}"
    if not ok:
        detail += f" msg={msg}"
    results.append(Result("期权下单", "POST",
                          "/api/internal/agent/option/order",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 03. 期权下单状态查询 ====================
    print("[03/19] 期权下单状态查询...", end=" ")
    d = get("/api/internal/agent/option/order/status",
            {"orderId": opt_order_id or "test"},
            OPT_AID, OPT_SUB)
    ok, code, msg = check(d)
    sd = d.get("data") or {}
    detail = f"completed={sd.get('completed')} ksoid={sd.get('keyStockOrderId')}"
    results.append(Result("期权下单状态查询", "GET",
                          "/api/internal/agent/option/order/status",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 04. 期权下单结果查询 ====================
    print("[04/19] 期权下单结果查询...", end=" ")
    d = post("/api/internal/agent/option/order/query",
             {"filter": {"contractType": "EUROPEAN_VANILLA", "keyStockOrderId": 973409},
              "pageNum": 1, "pageSize": 10},
             OPT_AID, OPT_SUB)
    ok, code, msg = check(d)
    total = d.get("data", {}).get("total", 0) if d.get("data") else 0
    detail = f"total={total}"
    results.append(Result("期权下单结果查询", "POST",
                          "/api/internal/agent/option/order/query",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 05. 期权撤单 ====================
    print("[05/19] 期权撤单...", end=" ")
    # 测试环境无可撤期权订单，用已知 ID 验证连通性
    d = post("/api/internal/agent/option/order/withdraw",
             {"keyStockOrderId": 271473},
             OPT_AID, OPT_SUB)
    ok, code, msg = check(d)
    detail = ""
    if code == 50003:
        detail = "测试环境无可用期权订单(预期行为)"
        ok = True  # 接口连通正常，只是没数据
    elif code == 403:
        detail = "agentid权限不足"
    results.append(Result("期权撤单", "POST",
                          "/api/internal/agent/option/order/withdraw",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 06. 期权撤单结果查询 ====================
    print("[06/19] 期权撤单结果查询...", end=" ")
    d = get("/api/internal/agent/option/order/withdrawResult",
            {"stockOrderCode": "OPTG-WFJJ202509030002"},
            OPT_AID, OPT_SUB)
    ok, code, msg = check(d)
    results.append(Result("期权撤单结果查询", "GET",
                          "/api/internal/agent/option/order/withdrawResult",
                          ok, code, msg))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 07. 可平仓合约列表 ====================
    print("[07/19] 可平仓合约列表...", end=" ")
    d = post("/api/internal/agent/option/position",
             {"filter": {"allowCloseOut": True}, "pageNum": 1, "pageSize": 15},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    total = d.get("data", {}).get("total", 0) if d.get("data") else 0
    detail = f"total={total}"
    results.append(Result("可平仓合约列表", "POST",
                          "/api/internal/agent/option/position",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 08. 期权平仓 ====================
    print("[08/19] 期权平仓...", end=" ")
    d = post("/api/internal/agent/option/order/close",
             {"notionalDelta": 1000000, "algoType": "LIMIT", "price": 15.1,
              "contractCode": "OPT-SZZSCF20260002"},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    close_ksoid = d.get("data", {}).get("keyStockOrderId") if d.get("data") else None
    detail = f"keyStockOrderId={close_ksoid}"
    results.append(Result("期权平仓", "POST",
                          "/api/internal/agent/option/order/close",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 09. 期权平仓订单查询 ====================
    print("[09/19] 期权平仓订单查询...", end=" ")
    d = post("/api/internal/agent/option/order/close/query",
             {"filter": {"tradeDate": datetime.now().strftime("%Y-%m-%d")},
              "pageNum": 1, "pageSize": 100},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    total = d.get("data", {}).get("total", 0) if d.get("data") else 0
    detail = f"total={total}"
    results.append(Result("期权平仓订单查询", "POST",
                          "/api/internal/agent/option/order/close/query",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 10. 期权平仓撤单 ====================
    print("[10/19] 期权平仓撤单...", end=" ")
    d = post("/api/internal/agent/option/order/close/withdraw",
             {"keyStockOrderId": close_ksoid or 1150076},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    detail = ""
    cw_code = None
    if ok and d.get("data"):
        cw_code = d["data"].get("stockOrderCode")
        detail = f"stockOrderCode={cw_code}"
    results.append(Result("期权平仓撤单", "POST",
                          "/api/internal/agent/option/order/close/withdraw",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 11. 期权平仓撤单结果查询 ====================
    print("[11/19] 期权平仓撤单结果查询...", end=" ")
    d = get("/api/internal/agent/option/order/close/withdrawResult",
            {"stockOrderCode": cw_code or "OPTG-SZZSCF202602040001"},
            COM_AID, "")
    ok, code, msg = check(d)
    results.append(Result("期权平仓撤单结果查询", "GET",
                          "/api/internal/agent/option/order/close/withdrawResult",
                          ok, code, msg))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 12. 互换下单 ====================
    print("[12/19] 互换下单...", end=" ")
    d = post("/api/internal/agent/trs/order",
             {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 200,
              "windCode": "0700.HK", "price": 400, "priceType": "LimitOrder",
              "orderDirection": "BUY",
              "shortName": "11125测试短名（张天琪专用）"},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    trs_koid = d.get("data", {}).get("keyOrderId") if d.get("data") else None
    detail = f"keyOrderId={trs_koid} async={d.get('data',{}).get('async') if d.get('data') else '?'}"
    results.append(Result("互换下单", "POST",
                          "/api/internal/agent/trs/order",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")
    time.sleep(2)

    # ==================== 13. 互换下单状态查询 ====================
    print("[13/19] 互换下单状态查询...", end=" ")
    d = post("/api/internal/agent/trs/order/status",
             [{"keyOrderId": trs_koid}],
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    dl = d.get("data", []) if d.get("data") else []
    detail = f"results={len(dl)}"
    if dl:
        detail += f" completed={dl[0].get('completed')}"
    results.append(Result("互换下单状态查询", "POST",
                          "/api/internal/agent/trs/order/status",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 14. 互换下单/撤单结果查询 ====================
    print("[14/19] 互换下单/撤单结果查询...", end=" ")
    d = post("/api/internal/agent/trs/order/query",
             {"keyOrderIdList": [trs_koid]},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    dl = d.get("data", []) if d.get("data") else []
    detail = f"results={len(dl)}"
    if dl:
        detail += f" status={dl[0].get('orderStatus')}"
    results.append(Result("互换下单/撤单结果查询", "POST",
                          "/api/internal/agent/trs/order/query",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 15. 互换撤单 ====================
    print("[15/19] 互换撤单...", end=" ")
    d = post("/api/internal/agent/trs/order/withdraw",
             {"orderList": [trs_koid]},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    detail = ""
    if d.get("data"):
        detail = f"results={len(d['data'])}"
    results.append(Result("互换撤单", "POST",
                          "/api/internal/agent/trs/order/withdraw",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 16. 互换改单 ====================
    print("[16/19] 互换改单...", end=" ")
    # 新下一个单用于改单
    d2 = post("/api/internal/agent/trs/order",
              {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 300,
               "windCode": "0700.HK", "price": 380, "priceType": "LimitOrder",
               "orderDirection": "BUY",
               "shortName": "11125测试短名（张天琪专用）"},
              COM_AID, COM_SUB)
    replace_koid = d2.get("data", {}).get("keyOrderId") if d2.get("data") else None
    time.sleep(2)
    d = post("/api/internal/agent/trs/order/replace",
             {"orderList": [{"keyOrderId": replace_koid, "priceType": "LimitOrder",
                             "quantity": 500, "price": 390, "algorithmType": "TWAP",
                             "startTime": datetime.now().strftime("%Y-%m-%d 11:00:00"),
                             "endTime": datetime.now().strftime("%Y-%m-%d 16:00:00")}]},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    detail = f"keyOrderId={replace_koid}"
    results.append(Result("互换改单", "POST",
                          "/api/internal/agent/trs/order/replace",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 17. 互换改单状态查询 ====================
    print("[17/19] 互换改单状态查询...", end=" ")
    d = post("/api/internal/agent/trs/order/replaceResults",
             {"orderList": [replace_koid]},
             COM_AID, COM_SUB)
    ok, code, msg = check(d)
    dl = d.get("data", []) if d.get("data") else []
    detail = f"results={len(dl)}"
    results.append(Result("互换改单状态查询", "POST",
                          "/api/internal/agent/trs/order/replaceResults",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 18. 企微群绑定交易对手查询 ====================
    print("[18/19] 企微群绑定交易对手查询...", end=" ")
    d = get("/api/internal/agent/getCtptyListByChatRoomId",
            {"type": "TRS"}, COM_AID, COM_SUB)
    ok, code, msg = check(d)
    n = len(d.get("data", [])) if d.get("data") else 0
    detail = f"{n}个交易对手"
    results.append(Result("企微群绑定交易对手查询", "GET",
                          "/api/internal/agent/getCtptyListByChatRoomId",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 19. 互换交易时间配置查询 ====================
    print("[19/19] 互换交易时间配置查询...", end=" ")
    d = get("/api/uniweb/rpa/trs/tradingHoursConfig",
            {}, COM_AID, COM_SUB)
    ok, code, msg = check(d)
    n = len(d.get("data", [])) if d.get("data") else 0
    detail = f"{n}条配置"
    results.append(Result("互换交易时间配置查询", "GET",
                          "/api/uniweb/rpa/trs/tradingHoursConfig",
                          ok, code, msg, detail))
    print("OK" if ok else f"FAIL({code})")

    # ==================== 汇总 ====================
    print("\n" + "=" * 70)
    print(f"{'#':<3} {'接口':<28} {'方法':<5} {'errCode':<8} {'状态':<6} {'备注'}")
    print("-" * 70)

    passed = 0
    failed = 0
    for i, r in enumerate(results, 1):
        status = "PASS" if r.ok else "FAIL"
        if r.ok:
            passed += 1
        else:
            failed += 1
        code_str = str(r.code) if r.code else "-"
        detail_str = r.detail[:50] if r.detail else ""
        print(f"{i:<3} {r.name:<28} {r.method:<5} {code_str:<8} {status:<6} {detail_str}")

    print(f"\n通过: {passed}/19  |  未通过: {failed}/19")
    if failed:
        print("\n未通过接口:")
        for r in results:
            if not r.ok:
                print(f"  [{r.method}] {r.path}")
                print(f"    errCode={r.code} msg={r.msg}")
                print(f"    detail={r.detail}")
        sys.exit(1)
    else:
        print("\n全部 19 个接口连通正常")


if __name__ == "__main__":
    main()
