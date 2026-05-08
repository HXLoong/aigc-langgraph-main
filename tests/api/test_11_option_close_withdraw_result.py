"""11. 期权平仓撤单结果查询  GET /api/internal/agent/option/order/close/withdrawResult
链式: 平仓下单 → 撤单 → 查结果
"""
from __future__ import annotations

from _utils import check, get, post, report, COM_AID, COM_SUB

print("11. 期权平仓撤单结果查询  GET /api/internal/agent/option/order/close/withdrawResult")

# Step 1: 平仓下单
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
ok2, code2, _ = check(d2)
cw_code = None
if ok2 and d2.get("data"):
    cw_code = d2["data"].get("stockOrderCode")
print(f"  [Step 2] 撤单 stockOrderCode={cw_code}  errCode={code2}")

# Step 3: 查撤单结果
d3 = get("/api/internal/agent/option/order/close/withdrawResult",
         {"stockOrderCode": cw_code or "OPTG-SZZSCF202602040001"},
         COM_AID, COM_SUB)
ok3, code3, msg3 = check(d3)
report("期权平仓撤单结果查询", ok3, code3)
