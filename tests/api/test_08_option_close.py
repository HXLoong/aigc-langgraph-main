"""08. 期权平仓  POST /api/internal/agent/option/order/close"""
from __future__ import annotations

from _utils import COM_AID, COM_SUB, check, post, report

print("08. 期权平仓  POST /api/internal/agent/option/order/close")

d = post("/api/internal/agent/option/order/close",
         {"notionalDelta": 1000000, "algoType": "LIMIT", "price": 15.1,
          "contractCode": "OPT-SZZSCF20260002"},
         COM_AID, COM_SUB)
ok, code, msg = check(d)
ksoid = d.get("data", {}).get("keyStockOrderId") if d.get("data") else None
report("期权平仓", ok, code, f"keyStockOrderId={ksoid}")
