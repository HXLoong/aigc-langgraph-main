"""10. 期权平仓撤单  POST /api/internal/agent/option/order/close/withdraw
链式: 平仓下单 → 撤单
"""
from __future__ import annotations

from _utils import COM_AID, COM_SUB, check, post, report

print("10. 期权平仓撤单  POST /api/internal/agent/option/order/close/withdraw")

# Step 1: 期权平仓
d1 = post("/api/internal/agent/option/order/close",
          {"notionalDelta": 1000000, "algoType": "LIMIT", "price": 15.1,
           "contractCode": "OPT-SZZSCF20260002"},
          COM_AID, COM_SUB)
ok1, code1, _ = check(d1)
ksoid = d1.get("data", {}).get("keyStockOrderId") if d1.get("data") else None
print(f"  [Step 1] 平仓下单 keyStockOrderId={ksoid}  errCode={code1}")

# Step 2: 平仓撤单
d2 = post("/api/internal/agent/option/order/close/withdraw",
          {"keyStockOrderId": ksoid or 1150076},
          COM_AID, COM_SUB)
ok2, code2, msg2 = check(d2)

cw_code = None
if ok2 and d2.get("data"):
    cw_code = d2["data"].get("stockOrderCode")
report("期权平仓撤单", ok2, code2, f"stockOrderCode={cw_code}")
